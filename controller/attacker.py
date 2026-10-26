"""Wallet test controller: barrier-synchronised withdrawals, K trials, invariant check, failing schedules saved.
usage: python controller.py K [N=2] [DELAY_MS=0] [LABEL=run]"""
import sys, json, time, pathlib, threading, httpx, psycopg2
BASE = "http://127.0.0.1:8000"
DSN = "dbname=rh user=rh password=rh host=localhost port=5432"
AMOUNT = 80
# each invariant is ONE select: zero rows = holds, >=1 row = violated
INVARIANTS = {
    "balance_nonneg": "select balance from wallet where balance < 0",
    "conservation": """select i.balance as initial, w.balance as final,
        coalesce((select sum(amount) from ops_log where endpoint='/withdraw' and status=200), 0) as withdrawn
        from initial_state i, wallet w
        where i.balance <> w.balance + coalesce((select sum(amount) from ops_log where endpoint='/withdraw' and status=200), 0)""",
}

def burst(cl, n, delay):
    """n identical withdrawals released together by a barrier; returns one record per request."""
    out = [None] * n; bar = threading.Barrier(n)
    def w(i):
        bar.wait()
        t0 = time.perf_counter()
        try:
            r = cl.post("/withdraw", params={"amount": AMOUNT}, headers={"X-Race-Delay": str(delay)}); st = r.status_code
        except Exception:
            st = -1
        out[i] = {"req": i, "status": st, "start_ms": round(t0 * 1000, 3), "end_ms": round(time.perf_counter() * 1000, 3)}
    ts = [threading.Thread(target=w, args=(i,)) for i in range(n)]
    [t.start() for t in ts]; [t.join() for t in ts]
    return out

def check(conn, invariants=INVARIANTS):
    """run every invariant read-only with a timeout; returns {name: rows-that-violate}"""
    res = {}
    with conn.cursor() as cur:
        for name, sql in invariants.items():
            cur.execute(sql); res[name] = [list(r) for r in cur.fetchall()]
    return res

def trial(cl, conn, n, delay, balance=100):
    cl.post("/reset", params={"balance": balance, "stock": 5})
    reqs = burst(cl, n, delay)
    state = cl.get("/state").json()
    return {"initial_state": {"balance": balance}, "requests": reqs, "final_state": state, "violations": check(conn)}

if __name__ == "__main__":
    K = int(sys.argv[1]); N = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    delay = int(sys.argv[3]) if len(sys.argv) > 3 else 0; label = sys.argv[4] if len(sys.argv) > 4 else "run"
    conn = psycopg2.connect(DSN); conn.set_session(readonly=True, autocommit=True)
    conn.cursor().execute("set statement_timeout = 5000")
    cl = httpx.Client(base_url=BASE, timeout=30, limits=httpx.Limits(max_connections=100))
    outdir = pathlib.Path(__file__).resolve().parent.parent / "runs" / label; outdir.mkdir(parents=True, exist_ok=True)
    counts = {k: 0 for k in INVARIANTS}; failing = 0
    for t in range(K):
        r = trial(cl, conn, N, delay)
        bad = [k for k, v in r["violations"].items() if v]
        for k in bad: counts[k] += 1
        if bad:
            failing += 1
            r.update({"trial": t, "n": N, "delay_ms": delay, "violated": bad})
            (outdir / f"failing_trial_{t:03d}.json").write_text(json.dumps(r, indent=2))
    print(f"{label} n={N} delay={delay}ms trials={K} trials_with_violation={failing} per_invariant={counts}")
