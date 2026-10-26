"""Isolation probes. Uploads a hostile-looking app, runs it the way GlitchHunter runs uploaded code, and prints what it could and could not do.
Run from the repo root with GH_DATABASE_URL set (a server user that may create roles); put a fake secret in the environment first to see it is not leaked:
    $env:GEMINI_API_KEY = "fake-secret-for-the-probe"; python samples/isolation_probe.py
Prints ALLOWED / denied per probe and exits 1 if something that must be denied was allowed."""
import os, sys, json, tempfile, pathlib, httpx
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from controller import config, attacker          # noqa: E402
from orchestrator import uploads, runner, dbsetup  # noqa: E402

APP = '''
import os
import psycopg2
from fastapi import FastAPI
app = FastAPI()

def q(sql):
    try:
        c = psycopg2.connect(os.environ["DATABASE_URL"]); c.autocommit = True; cur = c.cursor(); cur.execute(sql)
        try: r = str(cur.fetchall()[:2])[:70]
        except Exception: r = "ok"
        return "ALLOWED " + r
    except Exception as e:
        return "denied  " + str(e).strip().splitlines()[0][:70]

@app.get("/probe")
def probe():
    sec = [k for k in os.environ if any(t in k.upper() for t in ("KEY", "TOKEN", "SECRET", "ADMIN"))]
    return {
        "read a table of the main app (public.secret_demo)": q("select * from public.secret_demo"),
        "read ANOTHER uploaded project's table": q("select * from __OTHER__.items"),
        "create a schema": q("create schema evil"),
        "create a table in schema public": q("create table public.evil(x int)"),
        "read a server file (pg_read_file)": q("select pg_read_file('postgresql.conf')"),
        "read password hashes (pg_shadow)": q("select * from pg_shadow"),
        "become the main database user (SET ROLE)": q("set role ghadmin"),
        "create a role": q("create role evil2"),
        "run a shell command (COPY ... TO PROGRAM)": q("copy (select 1) to program 'echo hi'"),
        "create a table in its OWN schema (must work)": q("create table mine(x int)"),
        "who am I / which schema": q("select current_user, current_schema()"),
        "environment variable NAMES": sorted(os.environ),
        "env names that look like secrets": sec,
        "can see GEMINI_API_KEY": "GEMINI_API_KEY" in os.environ,
        "can see the main database URL": any("GH_DATABASE_URL" in k or "GH_ADMIN" in k for k in os.environ),
    }
'''

def make(cfg, name, app_text, files=None):
    d = pathlib.Path(tempfile.mkdtemp()); (d / "main.py").write_text(app_text, encoding="utf-8")
    m = uploads.create(cfg, name, [("main.py", (d / "main.py").read_bytes())])
    setup = {"app": "main:app", "file": "main.py", "func": "probe", "method": "GET", "path": "/probe", "body": "query", "burst": [{}, {}],
             "schema_sql": "CREATE TABLE items (id int PRIMARY KEY);", "seed_sql": "INSERT INTO items VALUES (1);", "db_env": "DATABASE_URL", "env": {}}
    uploads.save_setup(m["id"], setup); uploads.run_check(cfg, m["id"], lambda s: None)
    return m["id"]

def main():
    cfg = config.load(); other = make(cfg, "other-project", "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/probe')\ndef probe(): return 1\n")
    pid = make(cfg, "probe", APP.replace("__OTHER__", f"up_{other}"))
    meta = uploads.get(pid); sc = uploads.build_scenario(meta); sc["name"] = pid
    bad = []
    try:
        runner.ensure_running(cfg, sc)
        out = httpx.get(sc["base_url"] + "/probe", timeout=30).json()
    finally: runner.stop(sc)
    print(f"\nProbe project {pid}, isolated role {meta['role']}, schema up_{pid}\n")
    must_deny = [k for k in out if k.startswith(("read a table", "read ANOTHER", "create a schema", "create a table in schema", "read a server", "read password", "become", "create a role", "run a shell"))]
    for k, v in out.items():
        if k.startswith("environment variable NAMES"): print(f"  {k}: {v}"); continue
        flag = ""
        if k in must_deny and not str(v).startswith("denied"): flag = "   <-- PROBLEM"; bad.append(k)
        if k.startswith("create a table in its OWN") and not str(v).startswith("ALLOWED"): flag = "   <-- PROBLEM"; bad.append(k)
        if k.startswith("can see") and v: flag = "   <-- PROBLEM"; bad.append(k)
        print(f"  {k}: {v}{flag}")
    for p in (pid, other): uploads.delete(cfg, p)
    print("\nRESULT:", "all isolation checks held" if not bad else f"PROBLEMS: {bad}")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
