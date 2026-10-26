"""Starts and stops the uploaded app for a custom scenario. The app runs with the project's schema as its search_path and
WITHOUT our API keys in its environment. Its output goes to runs/projects/<id>/app.log so a start-up failure can be explained."""
import os, sys, time, atexit, subprocess, httpx
from controller import config

_procs = {}   # project_id -> Popen

def _alive(base_url):
    try: return httpx.get(f"{base_url}/openapi.json", timeout=2).status_code == 200
    except httpx.HTTPError: return False

def ensure_running(cfg, sc):
    """no-op for demo scenarios (started by hand); starts the uploaded app if it is not answering yet"""
    if not sc.get("custom") or _alive(sc["base_url"]): return
    pid = sc["project_id"]; stop(sc)
    env = config.test_env(os.environ, sc, cfg)
    logpath = config.PROJECTS / pid / "app.log"; log = open(logpath, "wb")
    port = sc["base_url"].rsplit(":", 1)[1]
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", f"{sc['entry']['module']}:{sc['entry']['var']}", "--port", port, "--log-level", "warning"],
                         cwd=sc["project_dir"], env=env, stdout=log, stderr=log)
    _procs[pid] = p
    for _ in range(100):
        if p.poll() is not None: break
        if _alive(sc["base_url"]): return
        time.sleep(0.2)
    log.flush(); tail = logpath.read_text(errors="replace").strip().splitlines()[-8:]
    stop(sc)
    raise RuntimeError("your app did not start. Last lines of its output: " + " | ".join(tail))

def stop(sc):
    p = _procs.pop(sc.get("project_id"), None)
    if p and p.poll() is None:
        p.terminate()
        try: p.wait(10)
        except subprocess.TimeoutExpired: p.kill()

atexit.register(lambda: [p.terminate() for p in _procs.values() if p.poll() is None])
