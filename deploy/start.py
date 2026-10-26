"""Container entry point (Render): the three demo apps on localhost and the API on 0.0.0.0:$PORT, in one container.
If any of them stops, everything stops and the container exits, so the platform restarts it.
Environment: GH_DATABASE_URL (required), PORT (set by Render, default 10000), GEMINI_API_KEY, GH_CORS_ORIGINS, GH_DISABLE_UPLOADS."""
import os, sys, time, signal, pathlib, subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
PORT = os.environ.get("PORT", "10000")
DEMOS = [("wallet", 8000, "vuln"), ("inventory", 8001, "vuln"), ("wallet-fixed", 8010, "fixed")]

def main():
    if not os.environ.get("GH_DATABASE_URL"):
        sys.exit("GH_DATABASE_URL is not set: link the database in render.yaml (or set it in the service's environment).")
    procs = []
    def launch(name, target, cwd, host, port, extra=None):
        p = subprocess.Popen([sys.executable, "-m", "uvicorn", target, "--host", host, "--port", str(port), "--log-level", "warning"],
                             cwd=cwd, env={**os.environ, **(extra or {})})
        procs.append((name, p)); print(f"started {name} on {host}:{port}", flush=True)
    for name, port, mode in DEMOS:
        app = "inventory_app:app" if name == "inventory" else "wallet_app:app"
        launch(name, app, ROOT / "apps", "127.0.0.1", port, {"MODE": mode})
    launch("api", "orchestrator.api:app", ROOT, "0.0.0.0", PORT)

    def stop(*_):
        for _, p in procs:
            if p.poll() is None: p.terminate()
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    while True:
        time.sleep(1)
        for name, p in procs:
            if p.poll() is not None:
                print(f"{name} exited with code {p.returncode}: stopping the container", flush=True); stop()
                for _, q in procs:
                    try: q.wait(8)
                    except subprocess.TimeoutExpired: q.kill()
                sys.exit(1)

if __name__ == "__main__":
    main()
