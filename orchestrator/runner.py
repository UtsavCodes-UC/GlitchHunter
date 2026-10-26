"""Starts and stops an uploaded app for a custom scenario, through controller.sandbox: a fresh working copy of its files, a minimal
environment, the project's own database role. Output goes to runs/projects/<id>/app.log so a start-up failure can be explained."""
import os, atexit, subprocess, httpx
from controller import config, sandbox, attacker

_procs = {}   # project_id -> (Popen, workdir)

def _alive(base_url):
    try: httpx.get(f"{base_url}/openapi.json", timeout=2); return True   # any HTTP answer counts (docs may be switched off)
    except httpx.HTTPError: return False

def ensure_running(cfg, sc, log=None):
    """no-op for demo scenarios (started by hand); starts the uploaded app if it is not answering yet.
    Before it starts, its schema is emptied and the project's schema SQL is run (an app that creates its own tables then does so)."""
    if not sc.get("custom") or _alive(sc["base_url"]): return
    say = log or (lambda m: None); pid = sc["project_id"]; stop(sc)
    say("Resetting the project's private schema and running the schema SQL")
    attacker.reset_schema(cfg, sc)
    say("Copying the project's files to a fresh temporary folder")
    work = sandbox.fresh_copy(sc["project_dir"], pid); logpath = config.PROJECTS / pid / "app.log"; port = sc["base_url"].rsplit(":", 1)[1]
    say(f"Starting {sc['app']} on port {port} (minimal environment, own database role)")
    p = sandbox.start(cfg, sc, work, sc["app"], port, logpath); _procs[pid] = (p, work)
    try: sandbox.wait_ready(p, sc["base_url"], logpath)
    except RuntimeError:
        stop(sc); raise
    say("The app answers")

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
    entry = _procs.pop(sc.get("project_id"), None)
    if entry: sandbox.kill(entry[0]); sandbox.cleanup(entry[1])
    if sc.get("base_url") and _alive(sc["base_url"]):   # started by another process: find it by its port
        for port in (sc["base_url"].rsplit(":", 1)[1], str(sc.get("candidate_port") or "")):
            if port: _kill_listener(port, sc["app"])

atexit.register(lambda: [(sandbox.kill(p), sandbox.cleanup(w)) for p, w in list(_procs.values())])
