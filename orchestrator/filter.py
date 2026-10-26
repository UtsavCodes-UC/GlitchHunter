"""Sequential filter for candidate invariants (wallet). Needs the vulnerable app running on :8000.
usage: python invariant_filter.py [S_SEQ=10] [K_CONC=50]
1. sequential workload (requests one at a time, no concurrency): a candidate that fires is WRONG -> DROPPED
2. concurrent workload (barrier burst): a candidate that never fires is UNINFORMATIVE
3. survivors are KEEP = proposed for human approval; recall is measured against a race oracle (evaluation only)"""
import sys, json, httpx, psycopg2
import controller as c

CANDIDATES = {**c.INVARIANTS,  # two correct ones plus deliberately over-strict ones, as an LLM might propose
    "no_rejected_requests": "select op_id from ops_log where status <> 200",
    "balance_unchanged": "select balance from wallet where balance <> (select balance from initial_state)",
    "single_withdrawal": "select 1 from ops_log where endpoint='/withdraw' and status=200 having count(*) <> 1",
}

def sequential_trial(cl, conn, n):
    cl.post("/reset", params={"balance": 100, "stock": 5})
    for _ in range(n):
        cl.post("/withdraw", params={"amount": c.AMOUNT})
    return c.check(conn, CANDIDATES)

if __name__ == "__main__":
    S = int(sys.argv[1]) if len(sys.argv) > 1 else 10; K = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    if len(sys.argv) > 3:  # optional: add the valid LLM-proposed invariants from a propose_invariants.py output file
        for inv in json.load(open(sys.argv[3]))["invariants"]:
            if inv.get("valid_sql"): CANDIDATES[f"llm{inv['sample']}_{inv['name']}"[:40]] = inv["sql"]
    conn = psycopg2.connect(c.DSN); 
    conn.set_session(readonly=True, autocommit=True)
    conn.cursor().execute("set statement_timeout = 5000")
    cl = httpx.Client(base_url=c.BASE, timeout=30, limits=httpx.Limits(max_connections=100))
    seq_fires = {k: 0 for k in CANDIDATES}
    for _ in range(S):
        for k, rows in sequential_trial(cl, conn, 2).items(): seq_fires[k] += bool(rows)
    conc_fires = {k: 0 for k in CANDIDATES}; hit_on_race = {k: 0 for k in CANDIDATES}; races = 0
    for _ in range(K):
        cl.post("/reset", params={"balance": 100, "stock": 5})
        reqs = c.burst(cl, 2, 0)
        race = sum(r["status"] == 200 for r in reqs) * c.AMOUNT > 100  # oracle: more money out than existed
        races += race
        for k, rows in c.check(conn, CANDIDATES).items():
            conc_fires[k] += bool(rows); hit_on_race[k] += bool(rows) and race
    print(f"sequential trials={S}, concurrent trials={K}, trials where the race really happened={races}")
    print(f"{'invariant':22s} seq_fires conc_fires recall_on_race  verdict")
    for k in CANDIDATES:
        recall = hit_on_race[k] / races if races else 0
        if seq_fires[k]: verdict = "DROPPED (fires sequentially)"
        elif conc_fires[k] == 0: verdict = "UNINFORMATIVE (never fires under concurrency)"
        elif recall >= 0.9: verdict = "KEEP -> human approval"
        else: verdict = f"WEAK (recall {recall:.0%} < 90%)"
        print(f"{k:22s} {seq_fires[k]:>4}/{S:<4} {conc_fires[k]:>4}/{K:<5} {hit_on_race[k]:>3}/{races:<3} {recall:>6.0%}  {verdict}")
