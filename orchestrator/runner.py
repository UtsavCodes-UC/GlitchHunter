"""Starts and stops the uploaded app for a custom scenario. The app runs with the project's schema as its search_path and
WITHOUT our API keys in its environment. Its output goes to runs/projects/<id>/app.log so a start-up failure can be explained."""
import os, sys, time, atexit, subprocess, httpx
from controller import config

_procs = {}   # project_id -> Popen

def _alive(base_url):
    try: httpx.get(f"{base_url}/openapi.json", timeout=2); return True   # any HTTP answer counts (docs may be switched off)
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

def _kill_listener(port, must_contain):
    """stop whatever serves this port IF it is a uvicorn process for this project's app (an app started by another API process,
    or left behind when a window was closed, keeps its files locked on Windows)"""
    if os.name != "nt": return
    ps = (f"Get-NetTCPConnection -State Listen -LocalPort {int(port)} -ErrorAction SilentlyContinue | ForEach-Object {{ "
          "$p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $_.OwningProcess); '{0}|{1}' -f $_.OwningProcess, $p.CommandLine }")
    try: out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired): return
    for line in out.splitlines():
        pid, _, cmd = line.partition("|")
        if pid.strip().isdigit() and "uvicorn" in cmd and must_contain in cmd:
            subprocess.run(["taskkill", "/PID", pid.strip(), "/F", "/T"], capture_output=True)

def stop(sc):
    p = _procs.pop(sc.get("project_id"), None)
    if p and p.poll() is None:
        p.terminate()
        try: p.wait(10)
        except subprocess.TimeoutExpired: p.kill()
    if sc.get("base_url") and _alive(sc["base_url"]):   # started by another process: find it by its port
        target = f"{sc['entry']['module']}:{sc['entry']['var']}"
        _kill_listener(sc["base_url"].rsplit(":", 1)[1], target)
        if sc.get("candidate_port"): _kill_listener(sc["candidate_port"], target)

atexit.register(lambda: [p.terminate() for p in _procs.values() if p.poll() is None])
