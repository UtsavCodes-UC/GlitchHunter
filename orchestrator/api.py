"""Orchestrator API (contract in docs/contracts.md). Run from the repo root:
python -m uvicorn orchestrator.api:app --port 9000        (needs GH_DATABASE_URL, and the target app running in MODE=vuln)"""
import os, json, time, base64, binascii, threading
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from controller import config, attacker
from . import repair as rep, store, projects, runner, service

app = FastAPI(title="GlitchHunter orchestrator")
_origins = ["http://localhost:3000", "http://127.0.0.1:3000"] + [o for o in os.environ.get("GH_CORS_ORIGINS", "").split(",") if o]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])
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
    try: return service.invariants_for_run(sc)
    except service.NoChecks as e: raise HTTPException(409, str(e))

def _start(cfg, sc):
    """uploaded apps are started on demand; demo apps are started by hand"""
    try: runner.ensure_running(cfg, sc)
    except RuntimeError as e: raise HTTPException(409, str(e))

@app.get("/health")
def health(): return {"ok": True}

@app.get("/scenarios")
def scenarios():
    cfg = config.load()
    return [{"id": k, "title": v.get("title"), "custom": bool(v.get("custom")), "endpoint": v["endpoint"], "race_n": v.get("race_n"),
             "invariants": len(store.load_invariants(k))} for k, v in cfg["scenarios"].items()]

# ---- Try your own app: upload a FastAPI app + setup SQL, pick an endpoint, get a scenario ----
@app.post("/projects")
def create_project(body: dict = Body(...)):
    cfg = config.load()
    try: content = base64.b64decode(body.get("content_b64", ""), validate=True)
    except (binascii.Error, ValueError): raise HTTPException(422, "the uploaded file could not be read")
    if not str(body.get("name", "")).strip() or not body.get("filename") or not str(body.get("setup_sql", "")).strip():
        raise HTTPException(422, "a name, an app file and the setup SQL are all required")
    with _One():
        try: return projects.create(cfg, str(body["name"]).strip()[:60], str(body["filename"]), content, str(body["setup_sql"]), body.get("db_env") or "DATABASE_URL")
        except ValueError as e: raise HTTPException(422, str(e))

@app.get("/projects")
def list_projects(): return projects.list_all()

@app.post("/projects/{pid}/scenario")
def make_scenario(pid, body: dict = Body(...)):
    try:
        sc = projects.create_scenario(pid, str(body.get("method", "")), str(body.get("path", "")), body.get("params") or {}, body.get("race_n") or 6, body.get("state"))
    except KeyError: raise HTTPException(404, "no such project")
    except ValueError as e: raise HTTPException(422, str(e))
    return {"id": sc["id"], "title": sc["title"], "endpoint": sc["endpoint"]}

@app.delete("/projects/{pid}")
def delete_project(pid):
    cfg = config.load()
    with _One():
        try: projects.delete(cfg, pid)
        except KeyError: raise HTTPException(404, "no such project")
    return {"ok": True}

@app.get("/scenarios/{sid}/invariants")
def invariants(sid):
    _sc(sid); return {"invariants": store.load_invariants(sid)}

@app.post("/scenarios/{sid}/propose")
def propose(sid, body: dict = Body(default={})):
    cfg, sc = _sc(sid)
    with _One():
        invs, stats = service.propose(cfg, sc, int(body.get("samples", 3)))
    return {"invariants": invs, "stats": stats}

@app.post("/scenarios/{sid}/filter")
def filter_(sid, body: dict = Body(default={})):
    cfg, sc = _sc(sid)
    with _One():
        _start(cfg, sc)
        invs = service.run_filter(cfg, sc, bool(body.get("include_decoys")), int(body.get("sequential_trials", 10)),
                                  int(body.get("trials", 50)), int(body.get("delay_ms", 0)))
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
        _start(cfg, sc)
        inv, human = _invariants_for_run(sc); run_id = f"r_{sid}_{int(time.time())}"
        summary, failing = attacker.attack(cfg, sc, inv, int(body.get("trials", 50)), body.get("n"), int(body.get("delay_ms", 0)), run_id)
    summary["invariants_used"] = list(inv); summary["human_approved"] = human
    return {"run_id": run_id, "summary": summary, "first_failing_trial": failing[0] if failing else None}

@app.post("/scenarios/{sid}/repair")
def repair(sid, body: dict = Body(default={})):
    cfg, sc = _sc(sid)
    with _One():
        _start(cfg, sc)
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
