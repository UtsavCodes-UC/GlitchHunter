"""Head-to-head: an LLM asked "is this fix correct?" versus actually running the fix against simultaneous requests.
usage (repo root): python -m orchestrator.head_to_head [K=30]      wallet scenario; needs GH_DATABASE_URL and an LLM key
The 7 candidate fixes are HAND-WRITTEN by us (3 correct, 4 subtly wrong). `intended` is our label from how each was built, not a measurement.
Execution verdict = controller.validate (regression + replay + K fresh trials at 0 and 30 ms) with two approved rules.
LLM verdict = one reply per fix from the configured model; read `model_used` in the output before comparing anything."""
import sys, re, json, time
from controller import config, attacker, validate
from . import llm, context, repair as rep

HEAD = '@app.post("/withdraw")\ndef withdraw(amount: int, x_race_delay: int = Header(0)):\n    with Conn() as c:\n        cur = c.cursor()\n'
TAIL = '        c.commit()\n    return {"ok": True}'
CHECK = '        bal = cur.fetchone()[0]\n        if bal < amount:\n            raise HTTPException(409, "insufficient")\n'

FIXES = [
    ("for_update", True, "lock the row while reading it",
     HEAD + '        cur.execute("select balance from wallet where id=1 for update")\n' + CHECK +
     '        hook(x_race_delay)\n        cur.execute("update wallet set balance=balance-%s where id=1", (amount,))\n' + TAIL),
    ("atomic_update", True, "single conditional UPDATE ... RETURNING",
     HEAD + '        cur.execute("update wallet set balance=balance-%s where id=1 and balance>=%s returning balance", (amount, amount))\n'
     '        if cur.fetchone() is None:\n            raise HTTPException(409, "insufficient")\n' + TAIL),
    ("advisory_lock", True, "transaction-level advisory lock with one fixed key",
     HEAD + '        cur.execute("select pg_advisory_xact_lock(42)")\n        cur.execute("select balance from wallet where id=1")\n' + CHECK +
     '        hook(x_race_delay)\n        cur.execute("update wallet set balance=%s where id=1", (bal - amount,))\n' + TAIL),
    ("check_before_lock", False, "reads and checks the balance, THEN takes the row lock and writes the stale value",
     HEAD + '        cur.execute("select balance from wallet where id=1")\n' + CHECK +
     '        cur.execute("select 1 from wallet where id=1 for update")\n        hook(x_race_delay)\n'
     '        cur.execute("update wallet set balance=%s where id=1", (bal - amount,))\n' + TAIL),
    ("lock_wrong_row", False, "FOR UPDATE on a row that does not exist, so nothing is locked",
     HEAD + '        cur.execute("select 1 from wallet where id=2 for update")\n        cur.execute("select balance from wallet where id=1")\n' + CHECK +
     '        hook(x_race_delay)\n        cur.execute("update wallet set balance=%s where id=1", (bal - amount,))\n' + TAIL),
    ("advisory_key_per_request", False, "advisory lock whose key is random, so two requests never share a lock",
     HEAD + '        cur.execute("select pg_advisory_xact_lock((random()*1000000000)::int)")\n        cur.execute("select balance from wallet where id=1")\n' + CHECK +
     '        hook(x_race_delay)\n        cur.execute("update wallet set balance=%s where id=1", (bal - amount,))\n' + TAIL),
    ("decrement_without_guard", False, "atomic decrement, but the balance check is a separate earlier read, so both can pass it (overdraft)",
     HEAD + '        cur.execute("select balance from wallet where id=1")\n' + CHECK +
     '        hook(x_race_delay)\n        cur.execute("update wallet set balance=balance-%s where id=1", (amount,))\n' + TAIL),
]

JUDGE = """You are reviewing a proposed fix for a race condition in a FastAPI + PostgreSQL endpoint. Two requests can arrive at the same instant.
Reason about every interleaving of two concurrent requests under PostgreSQL's default READ COMMITTED isolation.

ORIGINAL (buggy) CODE:
{orig}

PROPOSED FIX:
{fix}

Is the race condition fully fixed, with the same behaviour for single requests? Be careful: many fixes look right but are not.
Respond with ONLY this JSON: {{"fixed": true or false, "reason": "one or two sentences"}}"""

NAIVE = """Here is a FastAPI endpoint with a bug, and a proposed fix. Is the fix correct?

ORIGINAL:
{orig}

FIX:
{fix}

Respond with ONLY this JSON: {{"fixed": true or false, "reason": "one sentence"}}"""

def llm_verdict(orig, code, prompt=JUDGE):
    try:
        raw = llm.complete(prompt.format(orig=orig, fix=code), max_tokens=1500)
        v = json.loads(re.search(r"\{.*\}", raw, re.S).group(0)); return bool(v["fixed"]), str(v.get("reason", ""))[:300], llm.LAST_MODEL
    except Exception as e:
        return None, f"judge failed: {e!r}"[:200], llm.LAST_MODEL

def naive_only():
    """LLM-only pass with a lazy prompt (no instruction to reason about interleavings): shows how much the judge depends on prompting"""
    cfg = config.load(); sc = config.scenario(cfg, "wallet"); orig, _ = context.vuln_function(sc); rows = []
    for name, intended, what, code in FIXES:
        judged, why, model = llm_verdict(orig, code, NAIVE)
        rows.append({"fix": name, "intended_correct": intended, "llm_says_fixed": judged, "reason": why, "model_used": model})
        print(f"{name:26s} intended={'CORRECT' if intended else 'WRONG':7s} naive LLM says fixed={judged} | {why[:90]}", flush=True)
    bad = [r for r in rows if not r["intended_correct"]]
    s = {"prompt": "naive", "matches_intended": sum(r["llm_says_fixed"] == r["intended_correct"] for r in rows), "of": len(rows),
         "wrong_fixes_approved": sum(1 for r in bad if r["llm_says_fixed"]), "of_wrong": len(bad), "models_used": sorted({r["model_used"] for r in rows})}
    print("NAIVE SUMMARY", json.dumps(s))
    (config.ROOT / "runs" / f"head_to_head_naive_{int(time.time())}.json").write_text(json.dumps({"summary": s, "rows": rows}, indent=2), encoding="utf-8")

def main():
    if "--naive" in sys.argv: return naive_only()
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    cfg = config.load(); sc = config.scenario(cfg, "wallet"); orig, _ = context.vuln_function(sc)
    inv = {"wallet.conservation": attacker.conservation_sql(sc),
           "wallet.total_withdrawn_within_initial": "select 1 from initial_state i where i.balance < coalesce((select sum(amount) from ops_log where endpoint='/withdraw' and status=200), 0)"}
    rows = []
    for name, intended, what, code in FIXES:
        assert rep.static_check(code, sc) is None, f"{name} fails the static check"
        print(f"== {name} (intended {'CORRECT' if intended else 'WRONG'}: {what})", flush=True)
        ok, report, fb = validate.validate_candidate(cfg, sc, code, inv, k)
        judged, why, model = llm_verdict(orig, code)
        rows.append({"fix": name, "intended_correct": intended, "what": what, "execution_accepted": ok, "execution_reason": fb or "all checks passed",
                     "llm_says_fixed": judged, "llm_reason": why, "model_used": model})
        print(f"   execution: {'ACCEPTED' if ok else 'REJECTED'} | LLM: {judged} | {why[:110]}", flush=True)
    n = len(rows); ex = sum(r["execution_accepted"] == r["intended_correct"] for r in rows); lm = sum(r["llm_says_fixed"] == r["intended_correct"] for r in rows)
    bad = [r for r in rows if not r["intended_correct"]]
    summary = {"fixes": n, "k_fresh_trials_per_delay": k, "execution_matches_intended": ex, "llm_matches_intended": lm,
               "wrong_fixes": len(bad), "wrong_fixes_llm_approved": sum(1 for r in bad if r["llm_says_fixed"]), "wrong_fixes_execution_accepted": sum(1 for r in bad if r["execution_accepted"]),
               "llm_judge_failures": sum(r["llm_says_fixed"] is None for r in rows), "models_used": sorted({r["model_used"] for r in rows})}
    print("\nSUMMARY", json.dumps(summary, indent=2))
    p = config.ROOT / "runs" / f"head_to_head_{int(time.time())}.json"; p.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8"); print("saved", p)

if __name__ == "__main__": main()
