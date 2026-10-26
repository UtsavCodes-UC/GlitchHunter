"""Drives the seven sample projects through the REAL API: upload -> static scan -> setup -> setup test -> (hand-written check) -> attack -> delete.
Needs the API running (python -m uvicorn orchestrator.api:app --port 9100) with GH_DATABASE_URL pointing at a database where the server user may
create roles, and this script run from the repo root with the same environment:   python samples/verify.py [--api http://127.0.0.1:9100] [--write] [name ...]
--write also (re)writes each sample's setup.json and SETUP.md. The checks are written by hand here, so no AI key is needed."""
import io, json, sys, time, zipfile, pathlib, argparse
import httpx

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from orchestrator import store, dbsetup   # noqa: E402  (after the path tweak)
from controller import config            # noqa: E402

def burst(n, item): return [dict(item) for _ in range(n)]

def sql(*parts): return " ".join(parts)

SAMPLES = [
    {"dir": "01-bank-psycopg2", "title": "Bank (psycopg2, package layout, JSON body)", "route": ("POST", "/withdraw"), "verdict": "suspect", "racy": True, "use_suggested": True,
     "override": {"burst": burst(3, {"account_id": 1, "amount": 80})},
     "story": "Three people withdraw 80 from an account holding 100 at the same moment.",
     "check": "SELECT 1 FROM initial_accounts i, accounts a WHERE i.id = a.id AND i.balance <> a.balance + COALESCE((SELECT SUM((params->>'amount')::int) FROM ops_log WHERE endpoint = '/withdraw' AND status = 200), 0)"},
    {"dir": "02-tickets-sqlalchemy", "title": "Tickets (SQLAlchemy ORM, path + query values)", "route": ("POST", "/events/{event_id}/book"), "verdict": "suspect", "racy": True, "use_suggested": True,
     "override": {"db_scheme": "postgresql+psycopg2"},
     "story": "Four people book the last seat of a concert at the same moment.",
     "check": "SELECT 1 FROM initial_events i, events e WHERE i.id = e.id AND i.seats_left <> e.seats_left + COALESCE((SELECT SUM((params->>'seats')::int) FROM ops_log WHERE endpoint = '/events/{event_id}/book' AND status = 200), 0)"},
    {"dir": "03-giftcards-asyncpg", "title": "Gift cards (asyncpg, async, creates its own table, reads DB_URL)", "route": ("POST", "/giftcards/{code}/redeem"), "verdict": "suspect", "racy": True,
     "setup": {"app": "server:app", "file": "server.py", "func": "redeem", "method": "POST", "path": "/giftcards/{code}/redeem", "body": "json", "burst": burst(3, {"code": "GIFT50", "amount": 30}),
               "schema_sql": "", "seed_sql": "INSERT INTO giftcards VALUES ('GIFT50', 50);", "db_env": "DB_URL", "env": {}},
     "story": "Three people redeem 30 each from a gift card holding 50. The app creates its own table, so the schema SQL stays empty.",
     "check": "SELECT 1 FROM initial_giftcards i, giftcards g WHERE i.code = g.code AND i.balance <> g.balance + COALESCE((SELECT SUM((params->>'amount')::int) FROM ops_log WHERE status = 200), 0)"},
    {"dir": "04-transfer-two-accounts", "title": "Transfers (four DIFFERENT requests in one burst)", "route": ("POST", "/transfer"), "verdict": "suspect", "racy": True, "use_suggested": True,
     "override": {"burst": [{"from_id": 1, "to_id": 2, "amount": 80}, {"from_id": 1, "to_id": 3, "amount": 80}, {"from_id": 2, "to_id": 1, "amount": 10}, {"from_id": 3, "to_id": 1, "amount": 5}]},
     "story": "Four different transfers between three accounts arrive together; the total money must stay the same.",
     "check": "SELECT 1 WHERE (SELECT SUM(balance) FROM accounts) <> (SELECT SUM(balance) FROM initial_accounts)"},
    {"dir": "05-safe-shop", "title": "Safe shop (CORRECT: SELECT ... FOR UPDATE)", "route": ("POST", "/buy"), "verdict": "guarded", "racy": False, "use_suggested": True, "override": {},
     "story": "A correct app: the scan says guarded and the attack must find nothing (no false alarm).",
     "check": "SELECT 1 FROM initial_items i, items t WHERE i.id = t.id AND i.stock <> t.stock + COALESCE((SELECT SUM((params->>'qty')::int) FROM ops_log WHERE endpoint = '/buy' AND status = 200), 0)"},
    {"dir": "06-likes-single-file", "title": "Likes (a single .py file)", "single": "likes.py", "route": ("POST", "/posts/{post_id}/like"), "verdict": "suspect", "racy": True,
     "setup": {"app": "likes:app", "file": "likes.py", "func": "like", "method": "POST", "path": "/posts/{post_id}/like", "body": "query", "burst": burst(4, {"post_id": 1}),
               "schema_sql": "CREATE TABLE posts (id int PRIMARY KEY, likes int NOT NULL);", "seed_sql": "INSERT INTO posts VALUES (1, 0);", "db_env": "DATABASE_URL", "env": {}},
     "story": "Four people like the same post at the same moment; every like must be counted.",
     "check": "SELECT 1 FROM initial_posts i, posts p WHERE i.id = p.id AND i.likes + (SELECT COUNT(*) FROM ops_log WHERE status = 200) <> p.likes"},
    {"dir": "07-broken-app", "title": "Broken app (missing package + a file with a syntax error)", "route": ("POST", "/buy"), "verdict": "writes_or_read", "racy": None, "expect_setup": "error",
     "expect_warning": "helpers.py",
     "setup": {"app": "main:app", "file": "api/main.py", "func": "buy", "method": "POST", "path": "/buy", "body": "query", "burst": burst(2, {"qty": 1}),
               "schema_sql": "CREATE TABLE t (id int);", "seed_sql": "", "db_env": "DATABASE_URL", "env": {}},
     "story": "Nothing to attack: the scan warns about the unreadable file and the setup test fails with a clear message."},
]

def pack(s):
    d = HERE / s["dir"]
    if s.get("single"): return [("files", (s["single"], (d / s["single"]).read_bytes()))]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(d.rglob("*")):
            if f.is_file() and f.name != "SETUP.md" and "__pycache__" not in f.parts: z.write(f, f"{s['dir']}/{f.relative_to(d).as_posix()}")   # zipped WITH its top folder
    return [("files", (s["dir"] + ".zip", buf.getvalue()))]

def write_docs(s, setup):
    d = HERE / s["dir"]; flat = lambda x: json.dumps(x)
    expect = {True: "Run the attack: it should fail in most tries (more requests succeed than the data allows).", False: "Run the attack: it should NOT fail. The scan hint is `guarded` and no check fires.",
              None: "The setup test should fail with a clear message naming the missing package. Nothing to attack."}[s["racy"]]
    sql_note = ("Schema SQL and seed SQL are filled in automatically from `schema.sql`." if (d / "schema.sql").exists() and s.get("use_suggested") else "Schema SQL / seed SQL: type them in as shown below.")
    (d / "SETUP.md").write_text(
        f"# {s['title']}\n\n{s['story']}\n\n"
        f"## How to use it\n1. On the home page, **Your own code**: {'pick the file `' + s['single'] + '`' if s.get('single') else 'pick the folder `' + s['dir'] + '` (or drop it)'}.\n"
        f"2. In the scan table the endpoint `{s['route'][0]} {s['route'][1]}` should be labelled **{s['verdict'] if s['verdict'] != 'writes_or_read' else 'writes / read-only'}**. Click **Use this** on it.\n"
        f"3. Check the setup form against the values below. {sql_note}\n4. **Save and test the setup**. {expect}\n\n"
        f"## Setup values\n| field | value |\n|---|---|\n| How to start the app | `{setup['app']}` |\n| File / function | `{setup['file']}` / `{setup['func']}` |\n"
        f"| Method and path | `{setup['method']} {setup['path']}` |\n| Other values are sent as | {setup['body']} |\n| Requests sent together | `{flat(setup['burst'])}` |\n"
        f"| Environment variable for the database | `{setup['db_env']}` |\n| Database URL style | `{setup.get('db_scheme', 'postgresql')}` |\n\n"
        f"Schema SQL:\n```sql\n{setup['schema_sql'] or '-- (empty: the app creates its own tables)'}\n```\nSeed SQL:\n```sql\n{setup['seed_sql'] or '-- (none)'}\n```\n\n"
        f"Command line instead: `.\\glitchhunter upload samples\\{s['dir']}` then `.\\glitchhunter setup <id>` (uses the same suggested setup; the values above show what to change).\n", encoding="utf-8")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--api", default="http://127.0.0.1:9100"); ap.add_argument("--write", action="store_true"); ap.add_argument("--trials", type=int, default=20)
    ap.add_argument("names", nargs="*"); a = ap.parse_args()
    cl = httpx.Client(base_url=a.api, timeout=120); cfg = config.load(); results = []
    for s in SAMPLES:
        if a.names and s["dir"] not in a.names: continue
        row = {"sample": s["dir"], "problems": []}; results.append(row); bad = row["problems"].append
        r = cl.post("/api/uploads", files=pack(s), data={})
        if r.status_code != 200: bad(f"upload failed: {r.status_code} {r.text[:200]}"); continue
        p = r.json(); pid = p["id"]; row["id"] = pid; routes = p["scan"]["routes"]
        row["name"] = p["name"]
        m = next((x for x in routes if (x["method"], x["path"]) == s["route"]), None)
        if not m: bad(f"route {s['route']} not found by the scan: {[(x['method'], x['path']) for x in routes]}")
        elif s["verdict"] != "writes_or_read" and m["verdict"] != s["verdict"]: bad(f"scan hint was {m['verdict']}, expected {s['verdict']}")
        if s.get("expect_warning") and not any(s["expect_warning"] in w for w in p["scan"]["warnings"]): bad("scan did not warn about " + s["expect_warning"])
        setup = {**(p["suggested"] if s.get("use_suggested") else s["setup"]), **s.get("override", {})}
        if a.write: write_docs(s, setup)
        r = cl.put(f"/api/uploads/{pid}/config", json=setup)
        if r.status_code != 200: bad(f"config rejected: {r.text[:200]}"); cl.delete(f"/api/uploads/{pid}"); continue
        jid = cl.post(f"/api/uploads/{pid}/check").json()["job"]
        while True:
            j = cl.get(f"/api/uploads/{pid}/jobs/{jid}").json()
            if j["status"] != "running": break
            time.sleep(0.5)
        res = j["result"] or {}; row["setup_test"] = res.get("verdict")
        if s.get("expect_setup") == "error":
            if j["status"] != "error" and res.get("verdict") not in ("server error", "setup error"): bad(f"setup test should have failed, got {res.get('verdict')}")
            elif "notinstalled_pkg" not in json.dumps(res): bad("the failure message does not name the missing package: " + json.dumps(res)[:200])
        elif res.get("verdict") not in ("ok", "warning"): bad(f"setup test: {res.get('verdict')}: {res.get('message', '')[:200]}")
        elif s["racy"] is not None:
            store.save_invariants(pid, [{"id": f"{pid}.check", "name": "check", "english": "hand-written check", "sql": s["check"], "source": "manual", "status": "approved", "stats": {}}])
            att = cl.post(f"/scenarios/{pid}/attack", json={"trials": a.trials})
            if att.status_code != 200: bad(f"attack failed: {att.status_code} {att.text[:200]}")
            else:
                v = att.json()["summary"]["trials_with_violation"]; row["violations"] = f"{v}/{a.trials}"
                if s["racy"] and v == 0: bad("the race was not reproduced (0 violations)")
                if not s["racy"] and v > 0: bad(f"FALSE ALARM: {v} violations on a correct app")
        cl.delete(f"/api/uploads/{pid}")
        if cl.get(f"/api/uploads/{pid}").status_code != 404: bad("project still exists after delete")
        if dbsetup.exists(cfg, pid): bad("database role still exists after delete")
    print(f"\n{'sample':24s} {'scan':8s} {'setup test':12s} {'violations':11s} result")
    for r in results: print(f"{r['sample']:24s} {'ok' if not any('scan' in x or 'route' in x for x in r['problems']) else 'PROBLEM':8s} {str(r.get('setup_test')):12s} {str(r.get('violations', '-')):11s} {'PASS' if not r['problems'] else 'FAIL: ' + '; '.join(r['problems'])}")
    return 0 if all(not r["problems"] for r in results) else 1

if __name__ == "__main__":
    sys.exit(main())
