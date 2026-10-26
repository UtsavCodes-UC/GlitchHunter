"""Attacker: barrier-synchronised requests against a running app, K trials, rules checked in the real database.
The attacker records request statuses itself (ops_log) and the starting state (initial_state); the target app logs nothing.
usage (from the repo root): python -m controller.attacker SCENARIO TRIALS [N=2] [DELAY_MS=0]"""
import sys, json, time, threading, pathlib, httpx, psycopg2
from . import config

DDL = """create table if not exists ops_log(op_id serial primary key, endpoint text, amount int, qty int, user_id int, code text, status int);
create table if not exists initial_state(balance int, stock int);"""

def connect(cfg, readonly=False):
    c = psycopg2.connect(config.database_url(cfg)); c.set_session(readonly=readonly, autocommit=True)
    if readonly:
        with c.cursor() as cur: cur.execute("set statement_timeout = 5000")
    return c

def client(base_url):
    return httpx.Client(base_url=base_url, timeout=30, limits=httpx.Limits(max_connections=100))

def prepare(cl, admin, sc, reset_params=None):
    """reset the app, then (re)create and fill ops_log / initial_state. Returns the reset params used."""
    rp = {**sc["reset"]["params"], **(reset_params or {})}
    cl.post(sc["reset"]["path"], params=rp).raise_for_status()
    with admin.cursor() as cur:
        cur.execute(DDL); cur.execute("truncate ops_log restart identity"); cur.execute("delete from initial_state")
        cur.execute("insert into initial_state(balance, stock) values (%s, %s)",
                    [rp.get(c) if c in sc["initial_columns"] else None for c in ("balance", "stock")])
    return rp

def fire(cl, sc, n, delay, sequential=False):
    """n requests: released together by a barrier (default) or one after another. One record per request."""
    ep = sc["endpoint"]; out = [None] * n
    bar = None if sequential else threading.Barrier(n)
    def send(i):
        if bar: bar.wait()
        t = time.perf_counter()
        try: st = cl.request(ep["method"], ep["path"], params=ep["params"], headers={"X-Race-Delay": str(delay)}).status_code
        except Exception: st = -1
        out[i] = {"req": i, "method": ep["method"], "path": ep["path"], "params": dict(ep["params"]), "status": st,
                  "start_ms": t * 1000, "end_ms": time.perf_counter() * 1000}
    if sequential:
        for i in range(n): send(i)
    else:
        ts = [threading.Thread(target=send, args=(i,)) for i in range(n)]
        [t.start() for t in ts]; [t.join() for t in ts]
    base = min(r["start_ms"] for r in out)
    for r in out: r["start_ms"] = round(r["start_ms"] - base, 3); r["end_ms"] = round(r["end_ms"] - base, 3)
    return out

def record(admin, reqs):
    with admin.cursor() as cur:
        for r in reqs:
            p = r["params"]
            cur.execute("insert into ops_log(endpoint, amount, qty, user_id, code, status) values (%s,%s,%s,%s,%s,%s)",
                        (r["path"], p.get("amount"), p.get("qty"), p.get("user_id"), p.get("code"), r["status"]))

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
    return {"scenario": sc["name"], "n": n, "delay_ms": delay, "initial_state": {c: rp.get(c) for c in sc["initial_columns"]},
            "requests": reqs, "final_state": cl.get(sc["state_path"]).json(), "violations": check(ro, invariants)}

def race_happened(sc, t):
    """evaluation oracle only: more was taken out than existed (used to measure recall, never to flag a violation)"""
    o = sc["oracle"]; taken = sum(1 for r in t["requests"] if r["status"] == 200) * sc["endpoint"]["params"][o["param"]]
    return taken > t["initial_state"][o["initial"]]

def conservation_sql(sc):
    c = sc["conservation"]
    spent = f"coalesce((select sum({c['qty']}) from ops_log where endpoint='{sc['endpoint']['path']}' and status=200), 0)"
    return (f"select i.{c['initial']} as initial, t.{c['col']} as final, {spent} as taken from initial_state i, {c['table']} t "
            f"where i.{c['initial']} <> t.{c['col']} + {spent}")

def builtin(sc, decoys=False):
    """hand-written rules (source: manual): the conservation rule, plus optional over-strict decoys that the filter must drop"""
    rules = [{"id": f"{sc['name']}.conservation", "name": "conservation", "english": "what was there at the start equals what is left plus what successful requests took",
              "sql": conservation_sql(sc), "source": "manual", "status": "proposed", "stats": {}}]
    if decoys:
        rules.append({"id": f"{sc['name']}.no_rejected_requests", "name": "no_rejected_requests", "english": "DECOY: no request is ever rejected (too strict)",
                      "sql": "select op_id from ops_log where status <> 200", "source": "manual", "status": "proposed", "stats": {}})
    return rules

def attack(cfg, sc, invariants, trials, n=None, delay=0, run_id="run", save=True):
    """K barrier trials. invariants = {id: sql}. Failing trials are saved as replayable JSON under runs/<run_id>/."""
    admin, ro, cl = connect(cfg), connect(cfg, True), client(sc["base_url"])
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
