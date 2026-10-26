"""Attacker: barrier-synchronised requests against a running app, K trials, rules checked in the real database.
The attacker records request statuses itself (ops_log) and the starting state; the target app logs nothing.
Two kinds of scenario:
  demo   - the app has /reset and /state; the starting state goes into initial_state(balance, stock)
  custom - an uploaded app ("Try your own app"): a setup SQL recreates its tables, every table T is copied to snap_T (the state
           BEFORE the run), and the state shown to people is read from one table column. Each custom project has its own schema.
usage (from the repo root): python -m controller.attacker SCENARIO TRIALS [N=2] [DELAY_MS=0]   (demo scenarios)"""
import sys, json, time, threading, pathlib, httpx, psycopg2
from . import config

OPS_DDL = "create table if not exists ops_log(op_id serial primary key, endpoint text, amount int, qty int, user_id int, code text, status int);" \
          "alter table ops_log add column if not exists params jsonb;"
INITIAL_DDL = "create table if not exists initial_state(balance int, stock int);"

def connect(cfg, readonly=False, sc=None):
    url = config.database_url(cfg)
    if sc and sc.get("schema"): url = config.with_schema(url, sc["schema"])
    c = psycopg2.connect(url); c.set_session(readonly=readonly, autocommit=True)
    if readonly:
        with c.cursor() as cur: cur.execute("set statement_timeout = 5000")
    return c

def client(base_url):
    return httpx.Client(base_url=base_url, timeout=30, limits=httpx.Limits(max_connections=100))

def prepare(cl, admin, sc, reset_params=None):
    """put the app in its starting state and record that state. Returns the reset params used (demo) or {} (custom)."""
    if sc.get("custom"):
        with admin.cursor() as cur:
            cur.execute(sc["setup_sql"])  # recreates the app's tables with their starting rows
            cur.execute(OPS_DDL); cur.execute("truncate ops_log restart identity")
            for t in sc["tables"]:
                cur.execute(f"drop table if exists snap_{t}"); cur.execute(f"create table snap_{t} as select * from {t}")
        return {}
    rp = {**sc["reset"]["params"], **(reset_params or {})}
    cl.post(sc["reset"]["path"], params=rp).raise_for_status()
    with admin.cursor() as cur:
        cur.execute(OPS_DDL + INITIAL_DDL); cur.execute("truncate ops_log restart identity"); cur.execute("delete from initial_state")
        cur.execute("insert into initial_state(balance, stock) values (%s, %s)",
                    [rp.get(c) if c in sc["initial_columns"] else None for c in ("balance", "stock")])
    return rp

def read_state(admin, sc, snapshot=False):
    """custom scenarios: {column: value} summed over the chosen table (or its pre-run snapshot)"""
    st = sc["state"]; t = ("snap_" if snapshot else "") + st["table"]
    with admin.cursor() as cur:
        cur.execute(f"select sum({st['column']}) from {t}"); v = cur.fetchone()[0]
    if v is not None: v = int(v) if float(v) == int(v) else float(v)
    return {st["column"]: v}

def request_values(ep):
    """every value of a request in one flat dict: path values, query values and the JSON body's top-level fields (what ops_log.params holds)"""
    body = ep.get("json")
    return {**(ep.get("path_params") or {}), **ep["params"], **(body if isinstance(body, dict) else {})}

def concrete_path(ep):
    path = ep["path"]
    for k, v in (ep.get("path_params") or {}).items(): path = path.replace("{" + k + "}", str(v))
    return path

def fire(cl, sc, n, delay, sequential=False):
    """n requests: released together by a barrier (default) or one after another. One record per request."""
    ep = sc["endpoint"]; out = [None] * n; url = concrete_path(ep); hdrs = {**(ep.get("headers") or {}), "X-Race-Delay": str(delay)}
    bar = None if sequential else threading.Barrier(n)
    def send(i):
        if bar: bar.wait()
        t = time.perf_counter()
        try: st = cl.request(ep["method"], url, params=ep["params"] or None, json=ep.get("json"), headers=hdrs).status_code
        except Exception: st = -1
        out[i] = {"req": i, "method": ep["method"], "path": ep["path"], "params": request_values(ep), "status": st,
                  "start_ms": t * 1000, "end_ms": time.perf_counter() * 1000}
    if sequential:
        for i in range(n): send(i)
    else:
        ts = [threading.Thread(target=send, args=(i,)) for i in range(n)]
        [t.start() for t in ts]; [t.join() for t in ts]
    base = min(r["start_ms"] for r in out)
    for r in out: r["start_ms"] = round(r["start_ms"] - base, 3); r["end_ms"] = round(r["end_ms"] - base, 3)
    return out

def _num(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and abs(v) < 2**31 else None

def record(admin, reqs):
    with admin.cursor() as cur:
        for r in reqs:
            p = r["params"]
            cur.execute("insert into ops_log(endpoint, amount, qty, user_id, code, status, params) values (%s,%s,%s,%s,%s,%s,%s::jsonb)",
                        (r["path"], _num(p.get("amount")), _num(p.get("qty")), _num(p.get("user_id")),
                         str(p["code"]) if "code" in p else None, r["status"], json.dumps(p)))

def check(ro, invariants):
    """{invariant_id: rows that violate it}; None if the query itself failed (not counted as a violation)"""
    res = {}
    with ro.cursor() as cur:
        for k, sql in invariants.items():
            try: cur.execute(sql); res[k] = [list(x) for x in cur.fetchall()]
            except Exception: res[k] = None
    return res

def fired(violations):
    return [k for k, rows in violations.items() if rows]

def trial(cl, admin, ro, sc, invariants, n=None, delay=0, sequential=False, reset_params=None):
    n = n or sc["race_n"]; rp = prepare(cl, admin, sc, reset_params)
    reqs = fire(cl, sc, n, delay, sequential); record(admin, reqs)
    if sc.get("custom"): initial, final = read_state(admin, sc, snapshot=True), read_state(admin, sc)
    else: initial, final = {c: rp.get(c) for c in sc["initial_columns"]}, cl.get(sc["state_path"]).json()
    return {"scenario": sc["name"], "n": n, "delay_ms": delay, "initial_state": initial, "requests": reqs,
            "final_state": final, "violations": check(ro, invariants)}

def race_happened(sc, t):
    """evaluation oracle only: more was taken out than existed (used to measure recall, never to flag a violation).
    Uploaded apps have no oracle (we cannot know their meaning), so recall is not measured for them."""
    o = sc.get("oracle")
    if not o: return False
    taken = sum(1 for r in t["requests"] if r["status"] == 200) * sc["endpoint"]["params"][o["param"]]
    return taken > t["initial_state"][o["initial"]]

def sequential_signature(cfg, sc, cl, calls=3):
    """how the app behaves one request at a time: the status of each call and the final state. Used to check that a fix
    keeps everyday behaviour (the original app is the reference for uploaded projects)."""
    admin = connect(cfg, sc=sc)
    try:
        prepare(cl, admin, sc)
        statuses = [fire(cl, sc, 1, 0, sequential=True)[0]["status"] for _ in range(calls)]
        return {"statuses": statuses, "final": read_state(admin, sc)}
    finally: admin.close()

def conservation_sql(sc):
    c = sc["conservation"]
    spent = f"coalesce((select sum({c['qty']}) from ops_log where endpoint='{sc['endpoint']['path']}' and status=200), 0)"
    return (f"select i.{c['initial']} as initial, t.{c['col']} as final, {spent} as taken from initial_state i, {c['table']} t "
            f"where i.{c['initial']} <> t.{c['col']} + {spent}")

def builtin(sc, decoys=False):
    """hand-written rules (source: manual): the conservation rule, plus optional over-strict decoys that the filter must drop.
    Uploaded apps have no built-in rule: their rules must come from the AI and be approved by a person."""
    rules = []
    if sc.get("conservation"):
        rules.append({"id": f"{sc['name']}.conservation", "name": "conservation", "english": "what was there at the start equals what is left plus what successful requests took",
                      "sql": conservation_sql(sc), "source": "manual", "status": "proposed", "stats": {}})
    if decoys:
        rules.append({"id": f"{sc['name']}.no_rejected_requests", "name": "no_rejected_requests", "english": "DECOY: no request is ever rejected (too strict)",
                      "sql": "select op_id from ops_log where status <> 200", "source": "manual", "status": "proposed", "stats": {}})
    return rules

def attack(cfg, sc, invariants, trials, n=None, delay=0, run_id="run", save=True):
    """K barrier trials. invariants = {id: sql}. Failing trials are saved as replayable JSON under runs/<run_id>/."""
    admin, ro, cl = connect(cfg, sc=sc), connect(cfg, True, sc), client(sc["base_url"])
    outdir = config.ROOT / "runs" / run_id; failing, counts, races = [], {k: 0 for k in invariants}, 0
    if save: outdir.mkdir(parents=True, exist_ok=True)
    try:
        for i in range(trials):
            t = trial(cl, admin, ro, sc, invariants, n, delay); bad = fired(t["violations"]); races += race_happened(sc, t)
            for k in bad: counts[k] += 1
            if bad:
                t.update({"run_id": run_id, "trial": i}); failing.append(t)
                if save: (outdir / f"failing_trial_{i:03d}.json").write_text(json.dumps(t, indent=2, default=str), encoding="utf-8")
    finally:
        cl.close(); admin.close(); ro.close()
    summary = {"run_id": run_id, "scenario": sc["name"], "n": n or sc["race_n"], "delay_ms": delay, "trials": trials,
               "trials_with_violation": len(failing), "races_observed": races, "per_invariant": counts}
    if save: (outdir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary, failing

if __name__ == "__main__":
    cfg = config.load(); sc = config.scenario(cfg, sys.argv[1]); k = int(sys.argv[2])
    n = int(sys.argv[3]) if len(sys.argv) > 3 else None; delay = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    inv = {r["id"]: r["sql"] for r in builtin(sc)}
    s, _ = attack(cfg, sc, inv, k, n, delay, run_id=f"cli_{sys.argv[1]}_{int(time.time())}")
    print(json.dumps(s))
