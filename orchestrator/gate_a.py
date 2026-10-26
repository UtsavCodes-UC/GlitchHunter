"""Gate A demo in the terminal: propose -> filter -> approve -> attack -> repair -> negative control. Prints only numbers it measured.
usage (repo root, target app running in MODE=vuln): python -m orchestrator.gate_a wallet [--samples 3] [--k 50] [--decoys] [--no-auto-approve]
Auto-approve stands in for the human approval click: it approves survivors with recall >= 0.9 (say so when demoing)."""
import sys, json, time, argparse
from controller import config, attacker
from . import propose as proposer, filter as flt, repair as rep, store

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("scenario"); ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--k", type=int, default=50); ap.add_argument("--decoys", action="store_true"); ap.add_argument("--no-auto-approve", action="store_true")
    a = ap.parse_args(); cfg = config.load(); sc = config.scenario(cfg, a.scenario); out = {"scenario": a.scenario, "started": time.strftime("%H:%M:%S")}

    print("1. PROPOSE (LLM)"); invs, stats = proposer.propose(cfg, sc, a.samples); out["propose"] = stats; print("  ", stats)
    if a.decoys: invs += attacker.builtin(sc, decoys=True)
    else: invs += attacker.builtin(sc)
    print("2. FILTER (one-at-a-time vs simultaneous)")
    invs = flt.run_filter(cfg, sc, invs, 10, a.k); store.save_invariants(a.scenario, invs)
    for i in invs:
        s = i["stats"]; print(f"   {i['id']:45s} {i['status']:13s} seq_fires={s['sequential_fires']}/{s['sequential_trials']} conc_fires={s['concurrent_fires']}/{s['concurrent_trials']} recall={s['recall_on_race']}  [{i['source']}]")
    out["filter"] = invs
    if not a.no_auto_approve:
        for i in invs:
            if i["status"] == "proposed" and (i["stats"]["recall_on_race"] or 0) >= 0.9: store.set_status(a.scenario, i["id"], "approved")
    approved = store.approved(a.scenario); print("3. APPROVED:", list(approved) or "none (use the dashboard, or drop --no-auto-approve)")
    if not approved: return
    print("4. ATTACK the buggy app"); s, failing = attacker.attack(cfg, sc, approved, a.k, run_id=f"gateA_{a.scenario}_{int(time.time())}"); out["attack"] = s; print("  ", s)
    print("5. REPAIR (LLM patch, validated on a copy)"); res = rep.repair(cfg, sc, approved, a.k, 3, failing[0] if failing else None)
    for t in res["attempts"]:
        print(f"   attempt {t['attempt']} [{t.get('strategy')}] accepted={t['accepted']} {t.get('reason') or ''}");
        if t.get("validation"): print("     ", json.dumps(t["validation"]))
    print("6. NEGATIVE CONTROL (original buggy code through the same validator):", res["negative_control"])
    out["repair"] = res; print("GATE A:", "PASS" if res["accepted"] and res["negative_control"]["validator_working"] and s["trials_with_violation"] > 0 else "NOT PASSED")
    p = config.ROOT / "runs" / f"gate_a_{a.scenario}_{int(time.time())}.json"; p.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8"); print("saved", p)

if __name__ == "__main__": main()
