"""Operations shared by the API and the CLI, so both behave identically and share the same stored rules (runs/state/)."""
from controller import attacker
from . import propose as proposer, filter as flt, store

class NoChecks(Exception):
    """no approved check exists and the scenario has no built-in one (uploaded apps)"""

def propose(cfg, sc, samples=3):
    """ask the LLM for checks and store them; a human decision (approved / rejected) is never overwritten"""
    invs, stats = proposer.propose(cfg, sc, samples)
    keep = [i for i in store.load_invariants(sc["name"]) if i["status"] in ("approved", "rejected")]
    ids = {i["id"] for i in keep}
    store.save_invariants(sc["name"], keep + [i for i in invs if i["id"] not in ids])
    return store.load_invariants(sc["name"]), stats

def run_filter(cfg, sc, include_decoys=False, sequential_trials=10, trials=50, delay=0):
    invs = store.load_invariants(sc["name"])
    if include_decoys:
        have = {i["id"] for i in invs}; invs += [r for r in attacker.builtin(sc, decoys=True) if r["id"] not in have]
    elif not invs: invs = attacker.builtin(sc)
    invs = flt.run_filter(cfg, sc, invs, sequential_trials, trials, delay)
    store.save_invariants(sc["name"], invs)
    return invs

def invariants_for_run(sc):
    """({id: sql}, human_approved): the approved checks, else the built-in one; uploaded apps have no built-in one"""
    ap = store.approved(sc["name"])
    if ap: return ap, True
    fallback = {r["id"]: r["sql"] for r in attacker.builtin(sc)}
    if not fallback:
        raise NoChecks("Pick at least one check first (step 2): an uploaded app has no built-in check, so the AI must suggest some and you choose which to use.")
    return fallback, False
