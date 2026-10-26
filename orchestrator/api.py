"""Orchestrator API (contract in docs/contracts.md). Run from the repo root:
python -m uvicorn orchestrator.api:app --port 9000        (needs GH_DATABASE_URL, and the target app running in MODE=vuln)"""
import os, json, time, base64, binascii, threading
from fastapi import FastAPI, HTTPException, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from controller import config, attacker
from . import repair as rep, store, uploads, runner, service, llm

app = FastAPI(title="GlitchHunter orchestrator")
_origins = ["http://localhost:3000", "http://127.0.0.1:3000"] + [o for o in os.environ.get("GH_CORS_ORIGINS", "").split(",") if o]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])
UPLOADS_ON = os.environ.get("GH_DISABLE_UPLOADS", "") not in ("1", "true", "yes")   # public deployments switch uploads off: uploaded code runs on the server

def _need_uploads():
    if not UPLOADS_ON: raise HTTPException(403, "Uploading your own code is switched off on this deployment (GH_DISABLE_UPLOADS=1).")

_busy = uploads.BUSY  # attacks share one database; run one operation at a time

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
def health(): return {"ok": True, "provider": llm.PROVIDER, "model": llm.LAST_MODEL, "uploads": UPLOADS_ON}

@app.get("/scenarios")
def scenarios():
    cfg = config.load()
    def public_ep(ep):  # header values can be secrets (tokens): only their names leave the server
        return {**{k: val for k, val in ep.items() if k != "headers"}, "header_names": sorted((ep.get("headers") or {}))}
    stats = _run_stats()
    out = []
    for k, v in cfg["scenarios"].items():
        invs = store.load_invariants(k)
        out.append({"id": k, "title": v.get("title"), "custom": bool(v.get("custom")), "endpoint": public_ep(v["endpoint"]), "race_n": v.get("race_n"),
                    "burst": v.get("burst"), "invariants": len(invs), "rules_approved": sum(1 for i in invs if i["status"] == "approved"),
                    "failing_runs": stats["failing"].get(k, 0), "fixes_accepted": stats["fixes"].get(k, 0)})
    return out

def _run_stats():
    """what the saved runs on this machine say: failing tries found per scenario, and accepted fixes per scenario"""
    runs = config.ROOT / "runs"; failing, fixes = {}, {}
    for f in runs.glob("*/summary.json"):
        try: s = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError): continue
        if s.get("scenario"): failing[s["scenario"]] = failing.get(s["scenario"], 0) + int(s.get("trials_with_violation") or 0)
    for f in runs.glob("repair_*.json"):
        try: r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError): continue
        sid = f.stem[len("repair_"):].rsplit("_", 1)[0]
        if r.get("accepted"): fixes[sid] = fixes.get(sid, 0) + 1
    return {"failing": failing, "fixes": fixes}

# ---- Your own code: upload (static scan) -> setup -> "save and test" job -> a normal scenario ----
@app.post("/api/uploads")
async def upload(request: Request):
    _need_uploads()
    """multipart: field `name` (optional) and one or more `files` (a .zip, loose files, or a picked folder: the file name carries its relative path)"""
    lim = uploads.LIMITS(); form = await request.form()
    items = []
    for f in form.getlist("files"):
        data = await f.read(lim["file"] + 1 if not f.filename.lower().endswith(".zip") else lim["zip"] + 1)
        items.append((f.filename, data))
    if not items: raise HTTPException(422, "choose a .zip, some files or a folder")
    cfg = config.load()
    with _One():
        try: return uploads.create(cfg, str(form.get("name") or ""), items)
        except ValueError as e: raise HTTPException(422, str(e))

@app.get("/api/uploads")
def list_uploads(): return uploads.list_all() if UPLOADS_ON else []

def _up(pid):
    try: return uploads.get(pid)
    except KeyError: raise HTTPException(404, "no such project")

@app.get("/api/uploads/{pid}")
def get_upload(pid): return uploads.public(_up(pid), full=True)

@app.get("/api/uploads/{pid}/source")
def upload_source(pid, path: str, fn: str):
    _need_uploads()
    _up(pid)
    try: return uploads.source(pid, path, fn)
    except KeyError: raise HTTPException(404, "that function was not found")

@app.put("/api/uploads/{pid}/config")
def put_config(pid, body: dict = Body(...)):
    _need_uploads()
    _up(pid)
    with _One():
        try: return uploads.save_setup(pid, body)
        except ValueError as e: raise HTTPException(422, str(e))

@app.post("/api/uploads/{pid}/check")
def start_check(pid):
    _need_uploads()
    _up(pid); cfg = config.load()
    try: return {"job": uploads.start_check(cfg, pid)}
    except ValueError as e: raise HTTPException(422, str(e))

@app.get("/api/uploads/{pid}/jobs/{jid}")
def get_job(pid, jid):
    _need_uploads()
    try: return uploads.get_job(pid, jid)
    except KeyError: raise HTTPException(404, "no such job")

@app.delete("/api/uploads/{pid}")
def delete_upload(pid):
    _need_uploads()
    cfg = config.load(); _up(pid)
    with _One():
        try: uploads.delete(cfg, pid)
        except RuntimeError as e: raise HTTPException(409, str(e))
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
