"""Filter step. Run every candidate on (1) a one-at-a-time workload and (2) a simultaneous workload.
fires sequentially -> dropped (the rule itself is wrong); never fires under concurrency -> uninformative;
the rest stay `proposed` for human approval, with recall measured against a race oracle (evaluation only; PASS bar 0.9)."""
from controller import attacker

def run_filter(cfg, sc, invs, sequential_trials=10, trials=50, delay=0):
    cand = {i["id"]: i["sql"] for i in invs if i["status"] in ("proposed", "uninformative", "dropped")}
    admin, ro, cl = attacker.connect(cfg), attacker.connect(cfg, True), attacker.client(sc["base_url"])
    seq = {k: 0 for k in cand}; conc = {k: 0 for k in cand}; hit = {k: 0 for k in cand}; races = 0
    try:
        for _ in range(sequential_trials):
            t = attacker.trial(cl, admin, ro, sc, cand, sc["race_n"], 0, sequential=True)
            for k in attacker.fired(t["violations"]): seq[k] += 1
        for _ in range(trials):
            t = attacker.trial(cl, admin, ro, sc, cand, sc["race_n"], delay); race = attacker.race_happened(sc, t); races += race
            for k in attacker.fired(t["violations"]): conc[k] += 1; hit[k] += race
    finally: cl.close(); admin.close(); ro.close()
    for i in invs:
        k = i["id"]
        if k not in cand: continue
        recall = round(hit[k] / races, 3) if races else None
        i["stats"] = {"sequential_trials": sequential_trials, "sequential_fires": seq[k], "concurrent_trials": trials,
                      "concurrent_fires": conc[k], "races_observed": races, "recall_on_race": recall}
        if seq[k]: i["status"], i["note"] = "dropped", "fires on one-at-a-time runs, so the rule itself is wrong"
        elif not conc[k]: i["status"], i["note"] = "uninformative", "never fires under concurrency, cannot detect this bug"
        else:
            i["status"] = "proposed"
            i["note"] = ("passes the filter; needs human approval" if recall is not None and recall >= 0.9
                         else "fires under concurrency but recall is below 0.9 or no race was observed; review carefully")
    return invs
