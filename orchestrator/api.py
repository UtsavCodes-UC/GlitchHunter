"""Orchestrator API (contract in docs/contracts.md). Run from the repo root:
python -m uvicorn orchestrator.api:app --port 9000        (needs GH_DATABASE_URL, and the target app running in MODE=vuln)"""
import json, time, threading
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from controller import config, attacker
from . import propose as proposer, filter as flt, repair as rep, store

app = FastAPI(title="GlitchHunter orchestrator")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"], allow_methods=["*"], allow_headers=["*"])
_busy = threading.Lock()  # attacks share one database; run one operation at a time

def _sc(name):
    cfg = config.load()
    try: return cfg, config.scenario(cfg, name)
    except KeyError as e: raise HTTPException(404, str(e))

class _One:
    def __enter__(self):
        if not _busy.acquire(blocking=False): raise HTTPException(409, "another operation is running; try again in a moment")
    def __exit__(self, *a): _busy.release()

def _invariants_for_run(sc):
    ap = store.approved(sc["name"])
    return ap or {r["id"]: r["sql"] for r in attacker.builtin(sc)}, bool(ap)

@app.get("/health")
def health(): return {"ok": True}

@app.get("/scenarios")
def scenarios():
    cfg = config.load()
    return [{"id": k, "endpoint": v["endpoint"], "invariants": len(store.load_invariants(k))} for k, v in cfg["scenarios"].items()]

@app.get("/scenarios/{sid}/invariants")
def invariants(sid):
    _sc(sid); return {"invariants": store.load_invariants(sid)}

@app.post("/scenarios/{sid}/propose")
def propose(sid, body: dict = Body(default={})):
    cfg, sc = _sc(sid)
    with _One():
        invs, stats = proposer.propose(cfg, sc, int(body.get("samples", 3)))
        keep = [i for i in store.load_invariants(sid) if i["status"] in ("approved", "rejected")]  # never overwrite a human decision
        ids = {i["id"] for i in keep}
        store.save_invariants(sid, keep + [i for i in invs if i["id"] not in ids])
    return {"invariants": store.load_invariants(sid), "stats": stats}

@app.post("/scenarios/{sid}/filter")
def filter_(sid, body: dict = Body(default={})):
    cfg, sc = _sc(sid)
    with _One():
        invs = store.load_invariants(sid)
        if body.get("include_decoys"):
            have = {i["id"] for i in invs}; invs += [r for r in attacker.builtin(sc, decoys=True) if r["id"] not in have]
        elif not invs: invs = attacker.builtin(sc)
        invs = flt.run_filter(cfg, sc, invs, int(body.get("sequential_trials", 10)), int(body.get("trials", 50)), int(body.get("delay_ms", 0)))
        store.save_invariants(sid, invs)
    return {"invariants": invs}

@app.patch("/scenarios/{sid}/invariants/{inv_id}")
def set_status(sid, inv_id: str, body: dict = Body(...)):
    _sc(sid)
    if body.get("status") not in ("approved", "rejected", "proposed"): raise HTTPException(422, "status must be approved, rejected or proposed")
    try: return store.set_status(sid, inv_id, body["status"])
    except KeyError: raise HTTPException(404, f"no invariant {inv_id}")

@app.post("/scenarios/{sid}/attack")
def attack(sid, body: dict = Body(default={})):
    cfg, sc = _sc(sid)
    with _One():
        inv, human = _invariants_for_run(sc); run_id = f"r_{sid}_{int(time.time())}"
        summary, failing = attacker.attack(cfg, sc, inv, int(body.get("trials", 50)), body.get("n"), int(body.get("delay_ms", 0)), run_id)
    summary["invariants_used"] = list(inv); summary["human_approved"] = human
    return {"run_id": run_id, "summary": summary, "first_failing_trial": failing[0] if failing else None}

@app.post("/scenarios/{sid}/repair")
def repair(sid, body: dict = Body(default={})):
    cfg, sc = _sc(sid)
    with _One():
        inv, human = _invariants_for_run(sc)
        try: res = rep.repair(cfg, sc, inv, int(body.get("k", 50)), int(body.get("max_attempts", 3)))
        except RuntimeError as e: raise HTTPException(409, str(e))
    (config.ROOT / "runs").mkdir(exist_ok=True); (config.ROOT / "runs" / f"repair_{sid}_{int(time.time())}.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    res["human_approved_invariants"] = human
    return res

@app.get("/runs/{run_id}")
def run(run_id: str):
    d = config.ROOT / "runs" / run_id
    if not d.is_dir() or ".." in run_id: raise HTTPException(404, "no such run")
    summ = json.loads((d / "summary.json").read_text()) if (d / "summary.json").exists() else {}
    return {"summary": summ, "failing_trials": [json.loads(p.read_text()) for p in sorted(d.glob("failing_trial_*.json"))[:20]]}
