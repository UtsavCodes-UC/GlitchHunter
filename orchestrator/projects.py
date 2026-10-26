"""Uploaded projects ("Try your own app"). A project = a FastAPI app (one .py file or a .zip) + a setup SQL that creates its tables.
Everything lives under runs/projects/<id>/ (git-ignored): src/ (the uploaded code), project.json, scenario.json, app.log.
Each project gets its own PostgreSQL schema p_<id>, so it cannot touch the demo tables.
LIMITS (MVP): FastAPI + PostgreSQL, endpoints declared on the app object (@app.post("/x")) with query parameters, no path parameters,
the app must read its database URL from an environment variable. Uploaded code is run on THIS machine: only upload code you trust."""
import ast, io, json, re, secrets, shutil, socket, zipfile, pathlib
from controller import config, attacker

MAX_UPLOAD = 2_000_000
METHODS = {"get", "post", "put", "patch", "delete"}
SKIP_DIRS = {"venv", ".venv", "site-packages", "__pycache__", "node_modules", ".git", "tests", "test"}

def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:20] or "app"

def _dir(pid):
    if not re.fullmatch(r"[a-z0-9_]{1,40}", pid): raise KeyError(pid)
    return config.PROJECTS / pid

def _safe_extract(zf, dest):
    infos = [i for i in zf.infolist() if not i.filename.startswith("__MACOSX")]
    if len(infos) > 300: raise ValueError("the zip has too many files (limit 300)")
    root = dest.resolve(); total = 0
    for i in infos:
        if not str((dest / i.filename).resolve()).startswith(str(root)): raise ValueError("the zip contains an unsafe path")
        total += i.file_size
    if total > 20_000_000: raise ValueError("the zip is too large when unpacked (limit 20 MB)")
    for i in infos: zf.extract(i, dest)

def _py_files(src):
    return [p for p in src.rglob("*.py") if not (set(p.relative_to(src).parts[:-1]) & SKIP_DIRS)]

def _find_app(files, src):
    """(file, variable) of the first `x = FastAPI(...)`; main.py / app.py and shallow files first"""
    for p in sorted(files, key=lambda p: (p.name not in ("main.py", "app.py"), len(p.relative_to(src).parts))):
        try: tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError): continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                f = n.value.func; name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                tgt = [t.id for t in n.targets if isinstance(t, ast.Name)]
                if name == "FastAPI" and tgt: return p, tgt[0]
    return None, None

def _endpoints(files, src, app_var):
    out = []
    for p in files:
        try: text = p.read_text(encoding="utf-8"); tree = ast.parse(text)
        except (SyntaxError, UnicodeDecodeError): continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
            for d in fn.decorator_list:
                if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in METHODS
                        and isinstance(d.func.value, ast.Name) and d.func.value.id == app_var and d.args
                        and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str)): continue
                seg = ast.get_source_segment(text, fn) or ""
                verbs = {v.lower() for v in re.findall(r"\b(select|update|insert|delete)\b", seg, re.I)}
                params, sample = [], {}
                for a in fn.args.args:
                    ann = ast.unparse(a.annotation) if a.annotation else ""
                    params.append({"name": a.arg, "type": ann})
                    if a.arg in ("self", "request", "response") or ann in ("Request", "Response"): continue
                    if ann == "int": sample[a.arg] = 1
                    elif ann == "float": sample[a.arg] = 1.0
                    elif ann == "str": sample[a.arg] = "x"
                defaults = [ast.unparse(x) for x in fn.args.defaults]
                if any(x.startswith(("Header(", "Depends(", "Body(")) for x in defaults): sample = {k: v for k, v in sample.items()}
                path = d.args[0].value
                reason = "path parameters ({...}) are not supported yet" if "{" in path else ""
                rcw = "select" in verbs and bool(verbs & {"update", "insert", "delete"})
                out.append({"method": d.func.attr.upper(), "path": path, "function": fn.name, "file": str(p.relative_to(src)).replace("\\", "/"),
                            "params": params, "sample_params": sample, "supported": not reason, "unsupported_reason": reason,
                            "hint": ("reads, then writes to the database (the classic race pattern)" if rcw else
                                     "writes to the database" if verbs & {"update", "insert", "delete"} else
                                     "only reads from the database" if verbs else "no database access seen")})
    order = lambda e: (not e["supported"], 0 if "classic" in e["hint"] else 1 if e["hint"].startswith("writes") else 2)
    return sorted(out, key=order)

def _tables(sql):
    seen = []
    for t in re.findall(r"create\s+table\s+(?:if\s+not\s+exists\s+)?([A-Za-z_]\w*)", sql, re.I):
        if t.lower() not in [s.lower() for s in seen]: seen.append(t)
    return seen

def _suggest_state(sql, table):
    """first numeric column (not an id) of the table, to show 'before / after' numbers in the dashboard"""
    m = re.search(r"create\s+table\s+(?:if\s+not\s+exists\s+)?" + re.escape(table) + r"\s*\(", sql, re.I)
    if not m: return None
    depth, buf, cols = 1, "", []
    for ch in sql[m.end():]:
        if ch == "(": depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0: cols.append(buf); break
        if ch == "," and depth == 1: cols.append(buf); buf = ""; continue
        buf += ch
    for c in cols:
        w = c.strip().split()
        if len(w) >= 2 and re.match(r"(int|integer|bigint|smallint|numeric|decimal|real|double|serial|bigserial)", w[1], re.I) \
                and w[0].lower() != "id" and not w[0].lower().endswith("_id"):
            return {"table": table, "column": w[0]}
    return None

def _check_setup_sql(cfg, schema, sql, tables):
    admin = attacker.connect(cfg)
    try:
        with admin.cursor() as cur:
            cur.execute(f"create schema if not exists {schema}"); cur.execute(f"set search_path = {schema}")
            try: cur.execute(sql)
            except Exception as e: raise ValueError(f"your setup SQL failed: {str(e).strip().splitlines()[0]}")
            for t in tables:
                cur.execute("select 1 from information_schema.tables where table_schema = %s and table_name = %s", (schema, t.lower()))
                if not cur.fetchone(): raise ValueError(f"the setup SQL did not create table {t}")
    finally: admin.close()

def create(cfg, name, filename, content, setup_sql, db_env="DATABASE_URL"):
    if len(content) > MAX_UPLOAD: raise ValueError("the upload is too large (limit 2 MB)")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", db_env or ""): raise ValueError("the database environment variable name is not valid")
    tables = _tables(setup_sql)
    if not tables: raise ValueError("the setup SQL must contain at least one CREATE TABLE statement")
    pid = f"{_slug(name)}_{secrets.token_hex(2)}"; d = _dir(pid); src = d / "src"; src.mkdir(parents=True)
    try:
        fn = pathlib.Path(filename).name
        if fn.lower().endswith(".zip"):
            try: _safe_extract(zipfile.ZipFile(io.BytesIO(content)), src)
            except zipfile.BadZipFile: raise ValueError("that file is not a valid zip")
        elif fn.lower().endswith(".py"): (src / fn).write_bytes(content)
        else: raise ValueError("upload a .py file or a .zip of your app")
        files = _py_files(src); app_file, var = _find_app(files, src)
        if not app_file: raise ValueError("no FastAPI app found (looked for a line like `app = FastAPI()`)")
        eps = _endpoints(files, src, var)
        if not eps: raise ValueError(f"no endpoints found on `{var}` (looked for @{var}.post(\"/path\") style decorators)")
        schema = f"p_{pid}"; _check_setup_sql(cfg, schema, setup_sql, tables)
        alltext = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in files)
        warnings = [] if db_env in alltext else [f"Your code does not seem to read the environment variable {db_env}. GlitchHunter gives your app its "
                                                  f"database through that variable; if the connection string is hard-coded, the app will use the wrong database."]
        rel = app_file.relative_to(src).with_suffix("")
        meta = {"id": pid, "name": name, "filename": fn, "schema": schema, "db_env": db_env, "setup_sql": setup_sql, "tables": tables,
                "entry": {"file": str(app_file.relative_to(src)).replace("\\", "/"), "module": ".".join(rel.parts), "var": var},
                "endpoints": eps, "suggested_state": _suggest_state(setup_sql, tables[0]), "warnings": warnings}
        (d / "project.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return meta
    except Exception:
        shutil.rmtree(d, ignore_errors=True); raise

def get(pid):
    f = _dir(pid) / "project.json"
    if not f.exists(): raise KeyError(pid)
    return json.loads(f.read_text(encoding="utf-8"))

def list_all():
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(config.PROJECTS.glob("*/project.json"))] if config.PROJECTS.exists() else []

def _free_port(start, taken):
    p = start
    while True:
        if p not in taken:
            with socket.socket() as s:
                try: s.bind(("127.0.0.1", p)); return p
                except OSError: pass
        p += 1

def create_scenario(pid, method, path, params, race_n=6, state=None):
    meta = get(pid); ep = next((e for e in meta["endpoints"] if e["method"] == method.upper() and e["path"] == path), None)
    if not ep: raise ValueError("that endpoint was not found in your app")
    if not ep["supported"]: raise ValueError(ep["unsupported_reason"])
    state = state or meta["suggested_state"]
    if not state: raise ValueError("choose which table column to watch (no numeric column was found automatically)")
    if state["table"] not in meta["tables"]: raise ValueError("the state table must be one of the tables your setup SQL creates")
    if not 2 <= int(race_n) <= 20: raise ValueError("simultaneous requests must be between 2 and 20")
    taken = {int(re.search(r":(\d+)", u).group(1)) for sc in config.custom_scenarios().values() for u in (sc["base_url"], f"http://x:{sc['candidate_port']}")}
    port = _free_port(8200, taken); port2 = _free_port(port + 1, taken | {port})
    src = _dir(pid) / "src"
    sc = {"id": f"custom_{pid}", "custom": True, "title": meta["name"], "project_id": pid, "project_dir": str(src), "entry": meta["entry"],
          "schema": meta["schema"], "db_env": meta["db_env"], "setup_sql": meta["setup_sql"], "tables": meta["tables"],
          "app_file": str(src / ep["file"]), "base_url": f"http://127.0.0.1:{port}", "candidate_port": port2,
          "endpoint": {"method": ep["method"], "path": ep["path"], "params": params}, "state": state, "race_n": int(race_n)}
    (_dir(pid) / "scenario.json").write_text(json.dumps(sc, indent=2), encoding="utf-8")
    return sc

def delete(cfg, pid):
    d = _dir(pid)
    if not d.exists(): raise KeyError(pid)
    from . import runner
    sc = json.loads((d / "scenario.json").read_text(encoding="utf-8")) if (d / "scenario.json").exists() else None
    if sc: runner.stop(sc)
    admin = attacker.connect(cfg)
    try:
        with admin.cursor() as cur: cur.execute(f"drop schema if exists p_{pid} cascade")
    finally: admin.close()
    shutil.rmtree(d, ignore_errors=True); shutil.rmtree(config.ROOT / "runs" / "repair" / pid, ignore_errors=True)
