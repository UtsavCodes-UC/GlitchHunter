"""Uploaded projects ("Try your own app"). A project = a FastAPI app (one .py file or a .zip) + a setup SQL that resets its tables.
Everything lives under runs/projects/<id>/ (git-ignored): src/ (the uploaded code), project.json, scenario.json, app.log.
Each project gets its own PostgreSQL schema p_<id>, so it cannot touch the demo tables.
How it learns about the app: it is IMPORTED once in a subprocess (with the project's environment) and FastAPI is asked what it serves
(routes with their prefixes, parameters, JSON body schemas, auth needs, handler file and line). See controller/inject/inspect_app.py.
LIMITS: FastAPI + PostgreSQL (psycopg2 or synchronous SQLAlchemy); JSON or query/path parameters, one static auth header; no file/form
bodies, no cookie logins, no async database drivers. The app must read its database URL from an environment variable.
Uploaded code is run on THIS machine: only upload code you trust."""
import ast, io, json, os, re, secrets, shutil, socket, subprocess, sys, zipfile, pathlib
from controller import config, attacker
from . import appscan

MAX_UPLOAD = 2_000_000
MAX_TABLES = 30

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
    return [p for p in src.rglob("*.py") if not (set(p.relative_to(src).parts[:-1]) & appscan.SKIP_DIRS)]

def _find_app(files, src):
    """(file, variable) of the app object: `x = FastAPI(...)`, else a module-level `app = something(...)` in main.py / app.py (a factory)"""
    ordered = sorted(files, key=lambda p: (p.name not in ("main.py", "app.py"), len(p.relative_to(src).parts)))
    for p in ordered:
        try: tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError): continue
        for n in tree.body:
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                f = n.value.func; name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                tgt = [t.id for t in n.targets if isinstance(t, ast.Name)]
                if name == "FastAPI" and tgt: return p, tgt[0]
    for p in ordered:
        if p.name in ("main.py", "app.py"):
            try: tree = ast.parse(p.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError): continue
            for n in tree.body:
                if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and any(isinstance(t, ast.Name) and t.id == "app" for t in n.targets): return p, "app"
    return None, None

def _check_env(db_env, extra):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", db_env or ""): raise ValueError("the database environment variable name is not valid")
    extra = extra or {}
    if len(extra) > 20: raise ValueError("at most 20 extra environment variables")
    for k, v in extra.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(k)): raise ValueError(f"'{k}' is not a valid environment variable name")
        if k == db_env: raise ValueError(f"{k} is already set to the project's private database; remove it from the extra variables")
        if len(str(v)) > 500: raise ValueError(f"the value of {k} is too long")
    return {str(k): str(v) for k, v in extra.items()}

def _explain(err, db_env):
    """turn an import failure into something a person can act on"""
    t, m = err.get("type", ""), err.get("message", "")
    if t == "ModuleNotFoundError":
        pkg = m.split("'")[1] if "'" in m else m
        if pkg == "psycopg":
            return ("your app (SQLAlchemy 2.1+) picked the psycopg v3 driver for a plain postgresql:// URL, which is not installed here. Either set 'Database URL style' "
                    "to postgresql+psycopg2 (psycopg2 is installed), or run: pip install \"psycopg[binary]\".")
        return (f"your app needs the Python package '{pkg}', which is not installed here. Install it in the environment that runs GlitchHunter "
                f"(for example: pip install {pkg.split('.')[0]}, or pip install -r requirements.txt), then upload again.")
    if t == "KeyError": return f"your app needs the environment variable {m.strip(chr(39))}. Add it under 'Extra environment variables' and upload again."
    if "relative import" in m: return "your app uses package imports (from .x import y). Upload the whole folder as a .zip, not a single file."
    if t == "ValidationError" or "field required" in m.lower(): return "your app's settings are incomplete (a required setting is missing). Add it under 'Extra environment variables'. Details: " + m[:300]
    if t in ("OperationalError", "ProgrammingError"): return f"your app talked to the database while starting and failed: {m[:250]}. Does it read the database URL from {db_env}?"
    return f"your app could not be started for inspection ({t}: {m[:300]})"

def _inspect(cfg, src, module, var, pseudo):
    env = config.test_env(os.environ, {**pseudo, "pause_ms": 0}, cfg)
    try: res = subprocess.run([sys.executable, str(config.INJECT_DIR / "inspect_app.py"), module, var], cwd=src, env=env, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired: raise ValueError("importing your app took longer than 90 seconds (does it wait for something when it starts?)")
    for line in reversed((res.stdout or "").splitlines()):
        if line.startswith("GH_INSPECT_JSON:"): return json.loads(line[len("GH_INSPECT_JSON:"):])
        if line.startswith("GH_INSPECT_ERROR:"): raise ValueError(_explain(json.loads(line[len("GH_INSPECT_ERROR:"):]), pseudo["db_env"]))
    raise ValueError("your app did not report its routes. Output: " + ((res.stderr or res.stdout or "(nothing)").strip().splitlines() or ["(nothing)"])[-1][:300])

def _run_setup(cfg, schema, sql):
    admin = attacker.connect(cfg)
    try:
        with admin.cursor() as cur:
            cur.execute(f"create schema if not exists {schema}"); cur.execute(f"set search_path = {schema}")
            try: cur.execute(sql)
            except Exception as e: raise ValueError(f"your setup SQL failed: {str(e).strip().splitlines()[0]}")
            cur.execute("select table_name, column_name, data_type from information_schema.columns where table_schema = %s "
                        "and table_name not in ('ops_log', 'initial_state') and table_name not like 'snap\\_%%' order by table_name, ordinal_position", (schema,))
            cols = {}
            for t, c, d in cur.fetchall(): cols.setdefault(t, []).append({"name": c, "type": d})
    finally: admin.close()
    return cols

def public(meta):
    """what the browser may see: the extra environment variables' names, never their values"""
    return {**{k: v for k, v in meta.items() if k != "env"}, "env_names": sorted(meta.get("env", {}))}

def create(cfg, name, filename, content, setup_sql, db_env="DATABASE_URL", extra_env=None, db_scheme="postgresql"):
    if len(content) > MAX_UPLOAD: raise ValueError("the upload is too large (limit 2 MB)")
    extra = _check_env(db_env, extra_env)
    db_scheme = (db_scheme or "postgresql").strip()
    if not re.fullmatch(r"postgres(ql)?(\+[a-z0-9_]+)?", db_scheme): raise ValueError("the database URL style must look like postgresql or postgresql+psycopg2")
    if not str(setup_sql).strip(): raise ValueError("the setup SQL is required: it must reset your tables and insert a few starting rows")
    pid = f"{_slug(name)}_{secrets.token_hex(2)}"; d = _dir(pid); src = d / "src"; src.mkdir(parents=True); schema = f"p_{pid}"
    try:
        fn = pathlib.Path(filename).name
        if fn.lower().endswith(".zip"):
            try: _safe_extract(zipfile.ZipFile(io.BytesIO(content)), src)
            except zipfile.BadZipFile: raise ValueError("that file is not a valid zip")
        elif fn.lower().endswith(".py"): (src / fn).write_bytes(content)
        else: raise ValueError("upload a .py file or a .zip of your app")
        files = _py_files(src); app_file, var = _find_app(files, src)
        if not app_file: raise ValueError("no FastAPI app found (looked for a line like `app = FastAPI()` in your files)")
        rel = app_file.relative_to(src).with_suffix(""); module = ".".join(rel.parts)
        admin = attacker.connect(cfg)
        try:
            with admin.cursor() as cur: cur.execute(f"create schema if not exists {schema}")
        finally: admin.close()
        pseudo = {"custom": True, "db_env": db_env, "schema": schema, "env": extra, "db_scheme": db_scheme}
        info = _inspect(cfg, src, module, var, pseudo)          # imports the app: tables its code creates on start-up now exist
        columns = _run_setup(cfg, schema, setup_sql)             # then the setup SQL resets / seeds them
        if not columns: raise ValueError("no tables were found after running your setup SQL")
        if len(columns) > MAX_TABLES: raise ValueError(f"the setup SQL created {len(columns)} tables (limit {MAX_TABLES}); keep only the tables the endpoint needs")
        eps = appscan.endpoints(info, src)
        if not eps: raise ValueError("your app serves no endpoints that appear in its OpenAPI schema")
        alltext = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in files)
        warnings = []
        if db_env not in alltext and not any(db_env in v for v in extra.values()):
            warnings.append(f"Your code does not seem to read the environment variable {db_env}. GlitchHunter gives your app its database through that variable; if the connection string is hard-coded, the app will use the wrong database.")
        if re.search(r"create_async_engine|asyncpg|AsyncSession|aiopg|psycopg_pool", alltext) or (re.search(r"import psycopg\b|from psycopg import", alltext) and "sqlalchemy" not in alltext.lower()):
            warnings.append("Your app seems to use an async driver or the raw psycopg3 driver. GlitchHunter cannot slow down its database reads to make the race visible, so a race may be rare and hard to reproduce.")
        top = eps[0]; ftext = (appscan._func_text(str(src / top["file"]), top["lineno"], top["function"]) or "") if top["file"] else ""
        related = ftext + "\n" + appscan.related_code(src, ftext, top["function"])
        meta = {"id": pid, "name": name, "filename": fn, "schema": schema, "db_env": db_env, "db_scheme": db_scheme, "env": extra, "setup_sql": setup_sql, "tables": sorted(columns),
                "columns": columns, "entry": {"file": app_file.relative_to(src).as_posix(), "module": module, "var": var}, "endpoints": eps,
                "suggested_state": appscan.suggest_state(columns, related), "warnings": warnings}
        (d / "project.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return public(meta)
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        try:
            a = attacker.connect(cfg)
            with a.cursor() as cur: cur.execute(f"drop schema if exists {schema} cascade")
            a.close()
        except Exception: pass
        raise

def get(pid):
    f = _dir(pid) / "project.json"
    if not f.exists(): raise KeyError(pid)
    return json.loads(f.read_text(encoding="utf-8"))

def list_all():
    return [public(json.loads(f.read_text(encoding="utf-8"))) for f in sorted(config.PROJECTS.glob("*/project.json"))] if config.PROJECTS.exists() else []

def _free_port(start, taken):
    p = start
    while True:
        if p not in taken:
            with socket.socket() as s:
                try: s.bind(("127.0.0.1", p)); return p
                except OSError: pass
        p += 1

def create_scenario(pid, method, path, params=None, race_n=6, state=None, path_params=None, json_body=None, headers=None, qty_key=None, pause_ms=None):
    meta = get(pid); ep = next((e for e in meta["endpoints"] if e["method"] == method.upper() and e["path"] == path), None)
    if not ep: raise ValueError("that endpoint was not found in your app")
    if not ep["supported"]: raise ValueError("this endpoint is not supported yet: " + "; ".join(ep["unsupported_reasons"]))
    params = params if params is not None else ep["sample_params"]; path_params = path_params if path_params is not None else ep["sample_path_params"]
    json_body = json_body if json_body is not None else ep["sample_json"]
    if not isinstance(params, dict) or not isinstance(path_params, dict): raise ValueError("query and path values must be JSON objects")
    if json_body is not None and not isinstance(json_body, (dict, list)): raise ValueError("the JSON body must be an object or a list")
    missing = [n for n in re.findall(r"{(\w+)}", path) if n not in path_params]
    if missing: raise ValueError(f"give a value for the path parameter(s): {', '.join(missing)}")
    headers = {**(ep["required_headers"] or {}), **(headers or {})}
    for k, v in headers.items():
        if not re.fullmatch(r"[A-Za-z0-9-]{1,60}", str(k)): raise ValueError(f"'{k}' is not a valid header name")
        if "\n" in str(v) or "\r" in str(v): raise ValueError("header values must be one line")
    if ep["auth"] and ep["auth"]["header"] not in headers: raise ValueError(f"this endpoint requires login: provide the {ep['auth']['header']} header")
    state = state or meta["suggested_state"]
    if not state: raise ValueError("choose which table column to watch (no numeric column was found automatically)")
    if state["column"] not in [c["name"] for c in meta["columns"].get(state["table"], [])]: raise ValueError("the column to watch must be a column of one of your tables")
    if not 2 <= int(race_n) <= 20: raise ValueError("simultaneous requests must be between 2 and 20")
    pause = 25 if pause_ms is None else int(pause_ms)
    if not 0 <= pause <= 500: raise ValueError("the race pause must be between 0 and 500 ms")
    flat = {**path_params, **params, **(json_body if isinstance(json_body, dict) else {})}
    if qty_key and qty_key not in flat: raise ValueError(f"'{qty_key}' is not one of the request values ({', '.join(flat) or 'none'})")
    taken = {int(re.search(r":(\d+)", u).group(1)) for sc in config.custom_scenarios().values() for u in (sc["base_url"], f"http://x:{sc['candidate_port']}")}
    port = _free_port(8200, taken); port2 = _free_port(port + 1, taken | {port})
    src = _dir(pid) / "src"
    sc = {"id": f"custom_{pid}", "custom": True, "title": meta["name"], "project_id": pid, "project_dir": str(src), "entry": meta["entry"],
          "schema": meta["schema"], "db_env": meta["db_env"], "db_scheme": meta.get("db_scheme", "postgresql"), "env": meta.get("env", {}), "pause_ms": pause, "setup_sql": meta["setup_sql"], "tables": meta["tables"],
          "app_file": str(src / ep["file"]), "func": {"file": ep["file"], "name": ep["function"], "lineno": ep["lineno"]},
          "base_url": f"http://127.0.0.1:{port}", "candidate_port": port2,
          "endpoint": {"method": ep["method"], "path": ep["path"], "params": params, "path_params": path_params, "json": json_body, "headers": headers},
          "state": state, "qty_key": qty_key, "race_n": int(race_n)}
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
