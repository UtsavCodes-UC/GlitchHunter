"""Start an uploaded app as an isolated child process: a fresh working copy of its files, a minimal environment (see config.test_env),
its own process group, and on Linux/macOS resource limits (and, when GlitchHunter runs as root, an unprivileged user).
What this does NOT do: restrict outbound network access, or sandbox a process the way a container does. On Windows only the working copy,
the minimal environment and the process group apply (no rlimits, no user switch)."""
import os, sys, time, shutil, signal, pathlib, tempfile, subprocess, httpx
from . import config

WORK = config.ROOT / "runs" / "work"
IS_POSIX = os.name == "posix"
UNPRIV_UID = int(os.environ.get("GH_SANDBOX_UID", "65534"))     # "nobody", used only when we run as root

def fresh_copy(src_dir, tag):
    """a new temp working directory holding a copy of the project's files (the app may write files; they stay here and are deleted after)"""
    WORK.mkdir(parents=True, exist_ok=True)
    d = pathlib.Path(tempfile.mkdtemp(prefix=f"{tag}_", dir=WORK)); app = d / "app"
    shutil.copytree(src_dir, app)
    if IS_POSIX and os.geteuid() == 0:        # root drops to an unprivileged uid: it must own what it is about to run
        for p in [d, *d.rglob("*")]: os.chown(p, UNPRIV_UID, UNPRIV_UID)
    return d

def _prepare_child():                          # POSIX only, runs in the child between fork and exec
    import resource
    os.setsid()
    for lim, val in ((resource.RLIMIT_CPU, 900), (resource.RLIMIT_AS, 3 * 2**30), (resource.RLIMIT_FSIZE, 50 * 2**20),
                     (resource.RLIMIT_NOFILE, 1024), (resource.RLIMIT_CORE, 0)):
        try: resource.setrlimit(lim, (val, val))
        except (ValueError, OSError): pass
    if os.geteuid() == 0:
        try: resource.setrlimit(resource.RLIMIT_NPROC, (512, 512))
        except (ValueError, OSError): pass
        os.setgroups([]); os.setgid(UNPRIV_UID); os.setuid(UNPRIV_UID)

def start(cfg, sc, workdir, module, port, logpath):
    """launch uvicorn for `module` ("pkg.mod:attr") inside workdir/app; returns the Popen. Output goes to logpath."""
    app = pathlib.Path(workdir) / "app"; cwd = resolve_cwd(app, module.split(":")[0])
    env = config.test_env(os.environ, sc, cfg, home=workdir)
    log = open(logpath, "wb")
    kw = {"preexec_fn": _prepare_child} if IS_POSIX else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    try:
        return subprocess.Popen([sys.executable, "-m", "uvicorn", module, "--port", str(port), "--host", "127.0.0.1", "--log-level", "warning"]
                                + (["--factory"] if sc.get("factory") else []),
                                cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
    finally: log.close()

def resolve_cwd(app_root, module):
    """the folder uvicorn must run from: the project root, or the sub-folder that holds the module's top package (backend/app/main.py -> backend)"""
    rel = pathlib.Path(*module.split("."))
    for base in [app_root, *sorted((p for p in app_root.iterdir() if p.is_dir()), key=lambda p: p.name)]:
        if (base / rel).with_suffix(".py").exists() or (base / rel / "__init__.py").exists(): return base
    return app_root

def wait_ready(p, base_url, logpath, seconds=30):
    """True when the app answers HTTP (any status); raises RuntimeError with the last output lines if it exits or never answers"""
    end = time.time() + seconds
    while time.time() < end:
        if p.poll() is not None: break
        try: httpx.get(f"{base_url}/openapi.json", timeout=2); return True
        except httpx.HTTPError: time.sleep(0.25)
    tail = [l.strip() for l in pathlib.Path(logpath).read_text(errors="replace").splitlines() if l.strip()][-8:]
    kill(p)
    raise RuntimeError("the app did not start. Last lines of its output: " + (" | ".join(tail) if tail else "(no output)"))

def kill(p):
    """stop the app and everything it started"""
    if p is None or p.poll() is not None: return
    try:
        if IS_POSIX: os.killpg(p.pid, signal.SIGTERM)
        else: subprocess.run(["taskkill", "/PID", str(p.pid), "/F", "/T"], capture_output=True)
        p.wait(10)
    except (subprocess.TimeoutExpired, ProcessLookupError, PermissionError):
        try:
            if IS_POSIX: os.killpg(p.pid, signal.SIGKILL)
            else: p.kill()
        except (ProcessLookupError, PermissionError): pass

def cleanup(workdir):
    shutil.rmtree(workdir, ignore_errors=True)
