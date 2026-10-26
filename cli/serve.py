"""`serve` (the whole backend in one window), `ui` (the dashboard) and `stop` (stop everything).
Replaces starting 4 Python servers and the dashboard by hand. Logs go to runs/logs/. Windows-oriented (PowerShell / taskkill)."""
import os, sys, time, shutil, signal, subprocess, atexit, httpx
from controller import config

ROOT = config.ROOT
LOGS = ROOT / "runs" / "logs"
DEFAULT_DB = "postgresql://rh:rh@localhost:5432/rh"
# name, working dir, module:app, port, extra env, readiness path, note
SERVICES = [
    ("wallet (buggy)",    ROOT / "apps", "wallet_app:app",           8000, {"MODE": "vuln"},  "/openapi.json", "the app GlitchHunter attacks"),
    ("inventory (buggy)", ROOT / "apps", "inventory_app:app",        8001, {"MODE": "vuln"},  "/openapi.json", "second demo app"),
    ("wallet (fixed)",    ROOT / "apps", "wallet_app:app",           8010, {"MODE": "fixed"}, "/openapi.json", "for the red/green test"),
    ("API",               ROOT,          "orchestrator.api:app",     9000, {},                "/health",       "what the dashboard talks to"),
]
UI_PORT = 3000

def _ps(script):
    return subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=30).stdout

def listeners(ports):
    """{port: (pid, command line)} for processes listening on these ports (Windows)"""
    if os.name != "nt": return {}
    script = ("Get-NetTCPConnection -State Listen -LocalPort %s -ErrorAction SilentlyContinue | ForEach-Object { "
              "$p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $_.OwningProcess); '{0}|{1}|{2}' -f $_.LocalPort, $_.OwningProcess, $p.CommandLine }") % ",".join(map(str, ports))
    out = {}
    for line in _ps(script).splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3 and parts[0].isdigit(): out[int(parts[0])] = (int(parts[1]), parts[2])
    return out

def kill(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True)

def free_ports(ports, what, only=("uvicorn", "next", "node")):
    """stop leftover servers of ours on these ports; refuse to touch anything that does not look like one of ours"""
    held = listeners(ports); stopped, blocked = [], []
    for port, (pid, cmd) in sorted(held.items()):
        if any(w in cmd.lower() for w in only): kill(pid); stopped.append(port)
        else: blocked.append((port, cmd[:70]))
    if stopped: time.sleep(1.5)
    return stopped, blocked

def uploaded_ports():
    """ports uploaded apps may use: the whole range they are allocated from (8200 up), so orphans are found even when
    their scenario files are already gone"""
    ports = set(range(8200, 8300))
    for sc in config.custom_scenarios().values():
        for u in (sc["base_url"], f"http://x:{sc['candidate_port']}"): ports.add(int(u.rsplit(":", 1)[1]))
    return sorted(ports)

def _alive(url):
    try: return httpx.get(url, timeout=2).status_code < 500
    except httpx.HTTPError: return False

def _tail(path, n=6):
    try: return " | ".join(path.read_text(errors="replace").strip().splitlines()[-n:])
    except OSError: return ""

def serve(a, ui):
    """ui = the helpers (colours) from cli.main"""
    if not os.environ.get("GH_DATABASE_URL"):
        os.environ["GH_DATABASE_URL"] = DEFAULT_DB; print(ui.dim(f"GH_DATABASE_URL was not set: using {DEFAULT_DB}"))
    services = [s for s in SERVICES if not (a.no_fixed and s[3] == 8010) and not (a.no_inventory and s[3] == 8001)]
    ports = [s[3] for s in services]
    held = listeners(ports)
    if held:
        if not a.restart:
            lines = "\n".join(f"  port {p}: pid {pid}  {cmd[:70]}" for p, (pid, cmd) in held.items())
            raise ui.CliError(f"These ports are already in use (leftover servers from an earlier run?):\n{lines}\nRun `.\\glitchhunter serve --restart` to stop them and start fresh, or `.\\glitchhunter stop`.")
        stopped, blocked = free_ports(ports, "backend")
        if blocked: raise ui.CliError("A port is held by something that is not one of our servers, so I left it alone: " + "; ".join(f"{p}: {c}" for p, c in blocked))
        print(ui.dim(f"Stopped leftover servers on ports {stopped}."))
    LOGS.mkdir(parents=True, exist_ok=True); procs = []
    atexit.register(lambda: [p.terminate() for _, p, _ in procs if p.poll() is None])
    print(ui.bold("Starting the GlitchHunter backend..."))
    for name, cwd, target, port, extra, ready, note in services:
        log = open(LOGS / f"{name.split()[0]}_{port}.log", "wb")
        env = {**os.environ, **extra}
        if name == "API": env.setdefault("LLM_PROVIDER", "gemini")
        p = subprocess.Popen([sys.executable, "-m", "uvicorn", target, "--port", str(port), "--log-level", "warning"], cwd=cwd, env=env, stdout=log, stderr=log)
        procs.append((name, p, LOGS / f"{name.split()[0]}_{port}.log"))
    deadline = time.time() + 40; pending = {n: (p, lg, port, ready) for (n, p, lg), (_, _, _, port, _, ready, _) in zip(procs, services)}
    while pending and time.time() < deadline:
        for n in list(pending):
            p, lg, port, ready = pending[n]
            if p.poll() is not None:
                for _, q, _ in procs: q.terminate()
                raise ui.CliError(f"{n} stopped while starting (exit code {p.returncode}). Last log lines: {_tail(lg)}")
            if _alive(f"http://127.0.0.1:{port}{ready}"): del pending[n]
        time.sleep(0.4)
    if pending:
        for _, q, _ in procs: q.terminate()
        raise ui.CliError("did not become ready in time: " + ", ".join(pending) + ". Check runs\\logs\\")
    from orchestrator import llm
    key = "key set" if os.environ.get("GEMINI_API_KEY") else "NO key (Ollama fallback will be used)"
    print(ui.green(ui.bold("Backend is running.")))
    for name, _, _, port, _, _, note in services: print(f"  {name:18s} http://127.0.0.1:{port}   {ui.dim(note)}")
    print(f"  AI: {llm.PROVIDER} ({llm.MODEL}), GEMINI_API_KEY: {key}, Ollama fallback: {'on' if llm.OLLAMA_FALLBACK else 'off'}")
    print(ui.dim("  Logs: runs\\logs\\   |   Next: in a second terminal run  .\\glitchhunter ui"))
    print(ui.bold("Press Ctrl+C to stop everything."))
    warned = set()
    try:
        while True:
            time.sleep(1)
            for n, p, lg in procs:
                if p.poll() is not None and n not in warned:
                    warned.add(n); print(ui.red(f"! {n} stopped unexpectedly (exit code {p.returncode}). Last log lines: {_tail(lg)}"))
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        for _, p, _ in procs:
            if p.poll() is None: p.terminate()
        for _, p, _ in procs:
            try: p.wait(8)
            except subprocess.TimeoutExpired: p.kill()
        free_ports(uploaded_ports(), "uploaded apps")  # test copies of uploaded apps started by the API
        print("Stopped.")
    return 0

def stop(a, ui):
    ports = [s[3] for s in SERVICES] + uploaded_ports() + ([UI_PORT] if a.all else [])
    held = listeners(ports)
    if not held: print("Nothing of ours is running."); return 0
    stopped, blocked = free_ports(ports, "all")
    print(ui.green(f"Stopped servers on ports {stopped}.") if stopped else "Nothing to stop.")
    for p, c in blocked: print(ui.yellow(f"! port {p} is held by something that is not ours, left alone: {c}"))
    return 0

def _needs_build(d, env_text):
    bid = d / ".next" / "BUILD_ID"; stamp = d / ".next" / "gh_env_stamp"
    if not bid.exists() or not stamp.exists() or stamp.read_text() != env_text: return True
    built = bid.stat().st_mtime
    newest = max((f.stat().st_mtime for sub in ("app", "lib", "components", "mock") for f in (d / sub).rglob("*") if f.is_file()), default=0)
    newest = max(newest, (d / "package.json").stat().st_mtime, (d / "next.config.mjs").stat().st_mtime)
    return newest > built

def run_ui(a, ui):
    d = ROOT / "dashboard"
    if not shutil.which("npm"): raise ui.CliError("Node.js / npm was not found. Install Node 20+ from nodejs.org, then try again.")
    envf = d / ".env.local"
    if not envf.exists():
        envf.write_text("NEXT_PUBLIC_USE_MOCK=false\nNEXT_PUBLIC_API_URL=http://127.0.0.1:9000\n"); print(ui.dim("Created dashboard/.env.local (live mode)."))
    env_text = envf.read_text()
    if "USE_MOCK=true" in env_text: print(ui.yellow("! dashboard/.env.local says NEXT_PUBLIC_USE_MOCK=true: the dashboard will show MOCK data. Set it to false for the real thing."))
    held = listeners([UI_PORT])
    if held:
        if not a.restart:
            raise ui.CliError(f"Port {UI_PORT} is already in use ({list(held.values())[0][1][:70]}). Open http://localhost:{UI_PORT} if that is the dashboard, or run `.\\glitchhunter ui --restart` to replace it.")
        stopped, blocked = free_ports([UI_PORT], "ui")
        if blocked: raise ui.CliError(f"port {UI_PORT} is held by something that is not ours: {blocked[0][1]}")
    if not (d / "node_modules").exists():
        print(ui.bold("Installing dashboard packages (first time only)...")); subprocess.run("npm install", shell=True, cwd=d, check=True)
    if not _alive("http://127.0.0.1:9000/health"):
        print(ui.yellow("! The backend is not running yet. In another terminal run:  .\\glitchhunter serve"))
    if a.dev: cmd = "npm run dev"
    else:
        if a.rebuild or _needs_build(d, env_text):
            print(ui.bold("Building the dashboard (about 20 seconds)..."))
            r = subprocess.run("npm run build", shell=True, cwd=d)
            if r.returncode: raise ui.CliError("the dashboard build failed (see above).")
            (d / ".next" / "gh_env_stamp").write_text(env_text)
        cmd = "npm start"
    print(ui.green(ui.bold(f"Dashboard: http://localhost:{UI_PORT}")) + ui.dim("   (Ctrl+C to stop)"))
    p = subprocess.Popen(cmd, shell=True, cwd=d)
    try: p.wait()
    except KeyboardInterrupt: print("\nStopping the dashboard...")
    finally:
        kill(p.pid)
        free_ports([UI_PORT], "ui")
    return 0
