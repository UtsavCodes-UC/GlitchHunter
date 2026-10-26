"""Uploaded projects ("Your own code"). Flow: upload (files or a .zip) -> STATIC scan (nothing is run) -> a short setup (the endpoint, the
burst of requests, schema SQL, seed SQL) -> "Save and test the setup" (the app runs ONCE in isolation) -> the project is a normal scenario.
Files live under runs/projects/<id>/ (git-ignored): src/ (the uploaded text files), project.json, scenario.json (once set up), app.log.
Isolation: a database role + schema per project (orchestrator/dbsetup.py), a temp copy + minimal environment per run (controller/sandbox.py).
Uploaded code is NOT inspected by running it; it is only run after the person saved a setup."""
import ast, io, json, os, re, shutil, secrets, socket, stat, time, zipfile, pathlib, threading, traceback
from controller import config, attacker, sandbox
from . import scan as scanner, dbsetup, runner, store, appscan

def _limit(name, default): return int(os.environ.get(name, default))
LIMITS = lambda: {"zip": _limit("GH_UPLOAD_ZIP_MAX", 3_000_000), "file": _limit("GH_UPLOAD_FILE_MAX", 1_000_000), "total": _limit("GH_UPLOAD_TOTAL_MAX", 10_000_000),
                  "files": _limit("GH_UPLOAD_MAX_FILES", 400), "projects": _limit("GH_UPLOAD_MAX_PROJECTS", 25)}
TEXT_EXT = {".py", ".txt", ".md", ".sql", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".html", ".csv", ".rst"}
SKIP_DIRS = {"venv", ".venv", "env", "node_modules", ".git", "__pycache__", ".idea", ".vscode", "site-packages", ".mypy_cache", ".pytest_cache", ".tox", "dist", "build", ".ruff_cache"}
BUSY = threading.Lock()   # attacks share one database and one set of ports: one operation at a time
JOBS = {}

def _dir(pid):
    if not re.fullmatch(r"u[0-9a-f]{10}", pid): raise KeyError(pid)
    return config.PROJECTS / pid

def get(pid):
    f = _dir(pid) / "project.json"
    if not f.exists(): raise KeyError(pid)
    return json.loads(f.read_text(encoding="utf-8"))

def _save(meta): (_dir(meta["id"]) / "project.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

def public(meta, full=False):
    """what the browser may see: never the database role's password"""
    m = {k: v for k, v in meta.items() if k not in ("role_password", "scan", "suggested")}
    m["endpoints"] = len(meta["scan"]["routes"]); m["risky"] = meta["scan"]["risky"]
    if full: m["scan"] = meta["scan"]; m["suggested"] = meta["suggested"]
    return m

def list_all():
    return [public(json.loads(f.read_text(encoding="utf-8"))) for f in sorted(config.PROJECTS.glob("u*/project.json"))] if config.PROJECTS.exists() else []

# ---------------------------------------------------------------------- upload
def _clean_path(p):
    p = p.replace("\\", "/")
    if p.startswith("/") or re.match(r"^[A-Za-z]:", p) or "\x00" in p: raise ValueError(f"'{p}' is an absolute path: not accepted")
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if ".." in parts: raise ValueError(f"'{p}' contains '..': not accepted")
    return parts

def _expand(items, lim):
    """[(path, bytes)] from the upload: one .zip is unpacked (with its own limits), anything else is taken as it is"""
    if len(items) == 1 and items[0][0].lower().endswith(".zip"):
        name, data = items[0]
        if len(data) > lim["zip"]: raise ValueError(f"the zip is larger than {lim['zip'] // 1_000_000} MB")
        try: zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile: raise ValueError("that file is not a valid zip")
        out, total = [], 0
        for zi in zf.infolist():
            if zi.is_dir() or zi.filename.startswith("__MACOSX"): continue
            if stat.S_ISLNK(zi.external_attr >> 16): raise ValueError(f"the zip contains a symbolic link ({zi.filename}): not accepted")
            total += zi.file_size
            if total > lim["total"]: raise ValueError(f"the zip is larger than {lim['total'] // 1_000_000} MB when unpacked")
            if zi.file_size > lim["file"] * 4: continue                    # skipped below by size anyway; do not even read huge members
            with zf.open(zi) as fh: out.append((zi.filename, fh.read(lim["file"] + 1)))
        return out, pathlib.Path(name).stem
    return items, ""

def _derive_name(given, zipstem, paths):
    n = re.sub(r"[^\w .-]+", "-", (given or "").replace("\\", "/").split("/")[-1]).strip(" .-")[:60]
    if n: return n
    if zipstem: return re.sub(r"[^\w .-]+", "-", zipstem).strip(" .-")[:60] or "project"
    top = {p[0] for p in paths if len(p) > 1}
    if len(top) == 1: return re.sub(r"[^\w .-]+", "-", top.pop()).strip(" .-")[:60] or "project"
    py = next((p[-1] for p in paths if p[-1].endswith(".py")), "project.py")
    return pathlib.PurePosixPath(py).stem

def create(cfg, name, items):
    """items = [(relative path or file name, bytes)]. Returns the stored project (public form with the scan)."""
    lim = LIMITS()
    if len(list_all()) >= lim["projects"]: raise ValueError(f"at most {lim['projects']} projects can be stored: delete one first")
    items, zipstem = _expand(items, lim)
    files, skipped, total = {}, [], 0
    for raw, data in items:
        parts = _clean_path(raw)
        if not parts: continue
        if (set(parts[:-1]) & SKIP_DIRS) or any(x.startswith(".") for x in parts[:-1]): skipped.append(raw); continue
        ext = pathlib.PurePosixPath(parts[-1]).suffix.lower()
        if parts[-1].startswith(".") or ext not in TEXT_EXT: skipped.append(raw); continue
        if len(data) > lim["file"]: raise ValueError(f"{raw} is larger than {lim['file'] // 1000} KB")
        try: text = data.decode("utf-8-sig")
        except UnicodeDecodeError: raise ValueError(f"{raw} is not UTF-8 text")
        total += len(data); files[tuple(parts)] = text
        if total > lim["total"]: raise ValueError(f"the files add up to more than {lim['total'] // 1_000_000} MB")
        if len(files) > lim["files"]: raise ValueError(f"more than {lim['files']} files: upload only the app's folder (without venv, .git, node_modules)")
    stripped = ""
    if files and len({p[0] for p in files}) == 1 and all(len(p) > 1 for p in files):   # strip the single top folder (remembered, so a fix can be written back to the right file)
        stripped = next(iter(files))[0]; files = {p[1:]: t for p, t in files.items()}
    if not any(p[-1].endswith(".py") for p in files): raise ValueError("no Python (.py) file was found in the upload")
    pname = _derive_name(name, zipstem, list(files)); pid = "u" + secrets.token_hex(5); d = _dir(pid); src = d / "src"
    try:
        for p, text in files.items():
            f = src.joinpath(*p); f.parent.mkdir(parents=True, exist_ok=True); f.write_text(text, encoding="utf-8", newline="")
        rep = scanner.scan(src); sug = scanner.suggested_config(rep)
        meta = {"id": pid, "name": pname, "created": int(time.time()), "files": sorted("/".join(p) for p in files), "skipped": len(skipped), "scan": rep, "suggested": sug,
                "config": None, "status": "needs setup", "role": None, "role_password": None, "stripped": stripped}
        _save(meta)
    except Exception: shutil.rmtree(d, ignore_errors=True); raise
    return public(meta, full=True)

# ---------------------------------------------------------------------- setup (validated)
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

def _find_func(text, name, method, path):
    tree = ast.parse(text); cands = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if not cands: return None
    def match(n):
        return any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == method.lower() and d.args and isinstance(d.args[0], ast.Constant)
                   and path.endswith(str(d.args[0].value)) for d in n.decorator_list)
    n = next((c for c in cands if match(c)), cands[0])
    return min([d.lineno for d in n.decorator_list] + [n.lineno])

def validate_setup(meta, raw):
    """a clean setup dict, or ValueError with a message for the person"""
    if not isinstance(raw, dict): raise ValueError("the setup must be a JSON object")
    c = {}
    def text(k, maxlen, required=True):
        v = raw.get(k, ""); v = "" if v is None else v
        if not isinstance(v, str): raise ValueError(f"'{k}' must be text")
        if required and not v.strip(): raise ValueError(f"'{k}' is required")
        if len(v) > maxlen: raise ValueError(f"'{k}' is too long (limit {maxlen} characters)")
        return v.strip() if k not in ("schema_sql", "seed_sql") else v.replace("﻿", "")
    c["app"] = text("app", 200)
    if not re.fullmatch(r"[A-Za-z_][\w.]*:[A-Za-z_]\w*", c["app"]): raise ValueError("'app' must look like package.module:variable (for example app.main:app)")
    c["file"] = text("file", 300)
    if c["file"] not in meta["files"] or not c["file"].endswith(".py"): raise ValueError(f"'file' must be one of the uploaded .py files (got '{c['file']}')")
    c["func"] = text("func", 100)
    if not IDENT.fullmatch(c["func"]): raise ValueError("'func' must be a function name")
    c["method"] = text("method", 10).upper()
    if c["method"] not in ("GET", "POST", "PUT", "PATCH", "DELETE"): raise ValueError("'method' must be GET, POST, PUT, PATCH or DELETE")
    c["path"] = text("path", 200)
    if not c["path"].startswith("/") or re.search(r"\s", c["path"]): raise ValueError("'path' must start with / and contain no spaces (for example /orders/{order_id}/cancel)")
    c["body"] = raw.get("body", "json")
    if c["body"] not in ("json", "query"): raise ValueError("'body' must be json or query")
    burst = raw.get("burst")
    if not isinstance(burst, list) or not 2 <= len(burst) <= 50: raise ValueError("'burst' must be a list of 2 to 50 requests (JSON objects)")
    if not all(isinstance(b, dict) for b in burst): raise ValueError("every request in 'burst' must be a JSON object")
    if len(json.dumps(burst)) > 50_000: raise ValueError("'burst' is too large")
    holes = re.findall(r"{(\w+)}", c["path"])
    for i, b in enumerate(burst):
        miss = [h for h in holes if h not in b]
        if miss: raise ValueError(f"request {i + 1} in 'burst' has no value for the path placeholder(s): {', '.join(miss)}")
    c["burst"] = burst; c["schema_sql"] = text("schema_sql", 100_000, False); c["seed_sql"] = text("seed_sql", 100_000, False)
    c["db_env"] = raw.get("db_env") or "DATABASE_URL"
    if not isinstance(c["db_env"], str) or not IDENT.fullmatch(c["db_env"]): raise ValueError("'db_env' must be an environment variable name")
    env = raw.get("env") or {}
    if not isinstance(env, dict) or len(env) > 20: raise ValueError("'env' must be an object with at most 20 variables")
    for k, v in env.items():
        if not IDENT.fullmatch(str(k)): raise ValueError(f"'{k}' is not a valid environment variable name")
        if str(k) == c["db_env"]: raise ValueError(f"{k} is already set to the project's private database; remove it from 'env'")
        if len(str(v)) > 500: raise ValueError(f"the value of {k} is too long")
    c["env"] = {str(k): str(v) for k, v in env.items()}
    hdr = raw.get("headers") or {}
    if not isinstance(hdr, dict): raise ValueError("'headers' must be an object")
    for k, v in hdr.items():
        if not re.fullmatch(r"[A-Za-z0-9-]{1,60}", str(k)) or "\n" in str(v) or "\r" in str(v): raise ValueError(f"'{k}' is not a valid header")
    c["headers"] = {str(k): str(v) for k, v in hdr.items()}
    c["db_scheme"] = raw.get("db_scheme") or "postgresql"
    if not re.fullmatch(r"postgres(ql)?(\+[a-z0-9_]+)?", str(c["db_scheme"])): raise ValueError("'db_scheme' must look like postgresql or postgresql+psycopg2")
    try: c["pause_ms"] = int(raw.get("pause_ms", 25))
    except (TypeError, ValueError): raise ValueError("'pause_ms' must be a number")
    if not 0 <= c["pause_ms"] <= 500: raise ValueError("'pause_ms' must be between 0 and 500")
    src = _dir(meta["id"]) / "src"
    try: lineno = _find_func((src / c["file"]).read_text(encoding="utf-8"), c["func"], c["method"], c["path"])
    except SyntaxError as e: raise ValueError(f"{c['file']} has a syntax error (line {e.lineno}); the fix cannot be applied to it")
    if lineno is None: raise ValueError(f"the function {c['func']} was not found in {c['file']}")
    c["lineno"] = lineno
    module = c["app"].split(":")[0]
    if sandbox.resolve_cwd(src, module) is None or not any((b / pathlib.Path(*module.split("."))).with_suffix(".py").exists() or (b / pathlib.Path(*module.split(".")) / "__init__.py").exists()
                                                       for b in [src, *[p for p in src.iterdir() if p.is_dir()]]):
        raise ValueError(f"no file was found for the module '{module}' in your project")
    attr = c["app"].split(":")[1]; mod_file = next((b / pathlib.Path(*module.split(".")) for b in [src, *[p for p in src.iterdir() if p.is_dir()]]
                                                  if (b / pathlib.Path(*module.split("."))).with_suffix(".py").exists()), None)
    c["factory"] = False
    if mod_file:
        try:
            tree = ast.parse(mod_file.with_suffix(".py").read_text(encoding="utf-8"))
            c["factory"] = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == attr for n in tree.body)
        except SyntaxError: pass
    return c

def save_setup(meta_id, raw):
    meta = get(meta_id); c = validate_setup(meta, raw)
    sc_file = _dir(meta_id) / "scenario.json"
    if sc_file.exists():
        runner.stop(json.loads(sc_file.read_text(encoding="utf-8"))); sc_file.unlink()   # editing the setup: the old test no longer applies
    meta.update(config=c, status="needs setup"); _save(meta)
    return public(meta, full=True)

def _free_port(start, taken):
    p = start
    while True:
        if p not in taken:
            with socket.socket() as s:
                try: s.bind(("127.0.0.1", p)); return p
                except OSError: pass
        p += 1

def build_scenario(meta):
    c = meta["config"]; src = _dir(meta["id"]) / "src"
    taken = {int(re.search(r":(\d+)", u).group(1)) for sc in config.custom_scenarios().values() if sc["id"] != meta["id"] for u in (sc["base_url"], f"http://x:{sc['candidate_port']}")}
    old = (_dir(meta["id"]) / "scenario.json")
    if old.exists():
        o = json.loads(old.read_text(encoding="utf-8")); port, port2 = int(o["base_url"].rsplit(":", 1)[1]), o["candidate_port"]
    else: port = _free_port(8200, taken); port2 = _free_port(port + 1, taken | {port})
    return {"id": meta["id"], "custom": True, "title": meta["name"], "project_id": meta["id"], "project_dir": str(src), "app": c["app"], "factory": c["factory"],
            "schema": meta["role"] and f"up_{meta['id']}", "role": meta["role"], "role_password": meta["role_password"], "db_env": c["db_env"], "db_scheme": c["db_scheme"],
            "env": c["env"], "pause_ms": c["pause_ms"], "schema_sql": c["schema_sql"], "seed_sql": c["seed_sql"],
            "app_file": str(src / c["file"]), "func": {"file": c["file"], "name": c["func"], "lineno": c["lineno"]},
            "base_url": f"http://127.0.0.1:{port}", "candidate_port": port2,
            "endpoint": {"method": c["method"], "path": c["path"], "params": {}, "path_params": {}, "json": None, "body": c["body"], "headers": c["headers"]},
            "burst": c["burst"], "race_n": len(c["burst"])}

# ---------------------------------------------------------------------- the setup check (a job with a live log)
def start_check(cfg, pid):
    meta = get(pid)
    if not meta.get("config"): raise ValueError("save the setup first")
    job = {"id": secrets.token_hex(4), "project": pid, "status": "running", "log": [], "result": None}; JOBS[job["id"]] = job
    def say(m): job["log"].append({"t": round(time.time() - t0, 1), "msg": m})
    t0 = time.time()
    def work():
        try:
            if not BUSY.acquire(timeout=60): raise RuntimeError("another operation is running; try again in a moment")
            try: job["result"] = run_check(cfg, pid, say); job["status"] = "done"
            finally: BUSY.release()
        except attacker.SetupError as e: say(str(e)); job.update(status="error", result={"verdict": "setup error", "message": str(e)})
        except Exception as e:
            say(str(e)); job.update(status="error", result={"verdict": "setup error", "message": str(e)})
            if os.environ.get("GH_DEBUG"): traceback.print_exc()
    threading.Thread(target=work, daemon=True).start()
    return job["id"]

def get_job(pid, jid):
    j = JOBS.get(jid)
    if not j or j["project"] != pid: raise KeyError(jid)
    return j

def run_check(cfg, pid, say):
    meta = get(pid); say("Checking the saved setup")
    if not meta.get("role") or not meta.get("role_password"):
        say("Creating this project's private database role and schema")
        if meta.get("role"): dbsetup.teardown(cfg, pid)
        pv = dbsetup.provision(cfg, pid); meta.update(role=pv["role"], role_password=pv["password"]); _save(meta)
    sc = build_scenario(meta); sc["name"] = pid
    runner.stop(sc)
    try:
        runner.ensure_running(cfg, sc, say)
        admin, cl = attacker.connect(cfg, sc=sc), attacker.client(sc["base_url"])
        try:
            say("Resetting the tables and loading the seed rows"); attacker.prepare(cl, admin, sc)
            say(f"Sending the burst once: {len(sc['burst'])} requests released at the same moment")
            reqs = attacker.fire(cl, sc, len(sc["burst"]), 0); attacker.record(admin, reqs)
            after = attacker.dump_tables(admin); before = attacker.dump_tables(admin, "initial_")
        finally: cl.close(); admin.close()
        statuses = [r["status"] for r in reqs]; say(f"Responses: {statuses}")
        tail = ""
        try: tail = " | ".join([l.strip() for l in (config.PROJECTS / pid / "app.log").read_text(errors="replace").splitlines() if l.strip()][-4:])
        except OSError: pass
        if any(s >= 500 or s < 0 for s in statuses): verdict, msg = "server error", "your app answered with a server error (5xx) or did not answer. " + (f"Its last output: {tail}" if tail else "")
        elif not any(200 <= s < 300 for s in statuses) or 422 in statuses:
            verdict, msg = "warning", ("some or all requests were rejected" + (" (422: the request values do not match what the endpoint expects; check the body/query setting and the field names)" if 422 in statuses else "")
                                      + ". The test can still run, but a race needs at least some requests to succeed.")
        else: verdict, msg = "ok", "the burst ran and the app answered normally"
        say(("OK: " if verdict == "ok" else "Warning: " if verdict == "warning" else "Problem: ") + msg)
        if verdict != "server error":
            (_dir(pid) / "scenario.json").write_text(json.dumps(sc, indent=2), encoding="utf-8"); meta["status"] = "set up"
        else: meta["status"] = "needs setup"
        _save(meta)
        return {"verdict": verdict, "message": msg, "statuses": statuses, "initial_tables": before, "final_tables": after}
    finally: runner.stop(sc)

# ---------------------------------------------------------------------- other operations
def source(pid, path, fn):
    meta = get(pid)
    if path not in meta["files"] or not path.endswith(".py"): raise KeyError(path)
    text = (_dir(pid) / "src" / path).read_text(encoding="utf-8"); tree = ast.parse(text)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn:
            first = min([d.lineno for d in n.decorator_list] + [n.lineno])
            return {"path": path, "function": fn, "lineno": first, "code": "\n".join(text.splitlines()[first - 1:n.end_lineno])}
    raise KeyError(fn)

def delete(cfg, pid):
    d = _dir(pid)
    if not d.exists(): raise KeyError(pid)
    f = d / "scenario.json"; meta = get(pid)
    if f.exists(): runner.stop(json.loads(f.read_text(encoding="utf-8")))
    dbsetup.teardown(cfg, pid)
    shutil.rmtree(d, ignore_errors=True); runs = config.ROOT / "runs"
    for p in [runs / "state" / f"{pid}_invariants.json", *runs.glob(f"r_{pid}_*"), *runs.glob(f"repair_{pid}_*.json")]:
        shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
