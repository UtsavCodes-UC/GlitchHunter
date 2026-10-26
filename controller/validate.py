"""Validate a candidate fix: run it as a COPY of the app (never the original), then regression, replay of the failing
schedule, K fresh trials at two delays, and throughput. LLM-written code never sees our API keys.
Convention (demo apps): each endpoint function runs from its decorator to a line `# END-ENDPOINT`; without that marker the
function is assumed to end at the next `@x.method(` decorator or the end of the file (uploaded apps).
Uploaded projects (sc["custom"]): the whole project folder is copied, the endpoint file is patched, and the original app is the
reference for everyday behaviour."""
import os, re, sys, time, shutil, pathlib, threading, subprocess, contextlib, httpx
from . import config, attacker

MARK = "# END-ENDPOINT"

def decorator_re(ep):
    """matches @app.post("/path") (any object name, either quote style: ast.unparse turns " into ')"""
    return re.compile(r"@\w+\." + ep["method"].lower() + r"\(\s*[\"']" + re.escape(ep["path"]) + r"[\"']")

def region(src, ep):
    """(start, end) character offsets of the endpoint function: decorator .. end marker (or next decorator / end of file)"""
    m0 = decorator_re(ep).search(src)
    if not m0: raise ValueError(f"no @x.{ep['method'].lower()}({ep['path']!r}) decorator found in the app file")
    start = m0.start()
    m = src.find(MARK, start)
    if m != -1: return start, m
    n = re.search(r"^@\w+\.(get|post|put|patch|delete)\(", src[start + 1:], re.M)
    return start, (start + 1 + n.start()) if n else len(src)

def patched_source(src, ep, code):
    a, b = region(src, ep)
    return src[:a] + code.strip() + "\n\n" + src[b:]

def _env(cfg, sc):
    env = config.test_env(os.environ, sc, cfg); env["MODE"] = "vuln"
    return env

@contextlib.contextmanager
def server(sc, code=None, name="candidate_app", cfg=None):
    """run a copy of the app with the endpoint function replaced by `code` (None = unchanged) on candidate_port"""
    out = config.ROOT / "runs" / "repair"; out.mkdir(parents=True, exist_ok=True)
    if sc.get("custom"):
        src_dir = pathlib.Path(sc["project_dir"]); work = out / sc["project_id"]
        shutil.rmtree(work, ignore_errors=True); shutil.copytree(src_dir, work)
        target = work / pathlib.Path(sc["app_file"]).relative_to(src_dir); text = target.read_text(encoding="utf-8")
        if code: target.write_text(patched_source(text, sc["endpoint"], code), encoding="utf-8")
        cwd, module = work, f"{sc['entry']['module']}:{sc['entry']['var']}"
    else:
        src = config.app_path(sc).read_text(encoding="utf-8")
        (out / f"{name}.py").write_text(patched_source(src, sc["endpoint"], code) if code else src, encoding="utf-8")
        cwd, module = out, f"{name}:app"
    port = sc["candidate_port"]
    log = open(out / f"{name}.log", "wb")
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", module, "--port", str(port), "--log-level", "warning"],
                         cwd=cwd, env=_env(cfg, sc), stdout=log, stderr=log)
    cl = attacker.client(f"http://127.0.0.1:{port}")
    try:
        ready = False
        for _ in range(80):
            if p.poll() is not None: break
            try:
                if cl.get("/openapi.json").status_code == 200: ready = True; break
            except httpx.HTTPError: time.sleep(0.25)
        if not ready:
            log.flush(); tail = (out / f"{name}.log").read_text(errors="replace").strip().splitlines()[-6:]
            raise RuntimeError("candidate app did not start: " + " | ".join(tail))
        yield cl
    finally:
        cl.close(); p.terminate(); log.close()
        try: p.wait(10)
        except subprocess.TimeoutExpired: p.kill()

def regression(cl, sc):
    """demo apps: sequential cases from the config. Returns failure messages."""
    bad, ep = [], sc["endpoint"]
    for case in sc.get("regression", []):
        cl.post(sc["reset"]["path"], params={**sc["reset"]["params"], **case.get("reset", {})})
        for call in case["calls"]:
            got = cl.request(ep["method"], ep["path"], params=call["params"]).status_code
            if got != call["status"]: bad.append(f"{call['params']}: expected HTTP {call['status']}, got {got}")
        state = cl.get(sc["state_path"]).json()
        for k, v in case.get("state", {}).items():
            if state.get(k) != v: bad.append(f"after {case['calls']}: state {k} expected {v}, got {state.get(k)}")
    return bad

def regression_custom(cfg, sc, csc, cl):
    """uploaded apps: everyday behaviour = how the ORIGINAL app behaves one request at a time (statuses and final state)"""
    ref_cl = attacker.client(sc["base_url"])
    try: ref = attacker.sequential_signature(cfg, sc, ref_cl)
    finally: ref_cl.close()
    got = attacker.sequential_signature(cfg, csc, cl)
    if got != ref:
        return [f"one request at a time, the original returned {ref['statuses']} and ended at {ref['final']}, "
                f"but the fix returned {got['statuses']} and ended at {got['final']}"]
    return []

def trials(cfg, sc, cl, invariants, k, delay):
    """k fresh barrier trials on the candidate; returns (trials_with_violation, names of violated invariants)"""
    admin, ro = attacker.connect(cfg, sc=sc), attacker.connect(cfg, True, sc); fails, names = 0, set()
    try:
        for _ in range(k):
            bad = attacker.fired(attacker.trial(cl, admin, ro, sc, invariants, sc["race_n"], delay)["violations"])
            fails += bool(bad); names.update(bad)
    finally: admin.close(); ro.close()
    return fails, sorted(names)

def throughput(sc, cl, threads=16, per=25):
    tp, ep = sc["throughput"], sc["endpoint"]
    cl.post(sc["reset"]["path"], params={**sc["reset"]["params"], **tp["reset"]})
    def w():
        for _ in range(per): cl.request(ep["method"], ep["path"], params=tp["params"])
    ts = [threading.Thread(target=w) for _ in range(threads)]; t0 = time.perf_counter()
    [t.start() for t in ts]; [t.join() for t in ts]
    return round(threads * per / (time.perf_counter() - t0), 1)

def validate_candidate(cfg, sc, code, invariants, k=50, schedule=None):
    """returns (accepted, report in the contract's `validation` shape, feedback text for the next attempt)"""
    schedule = schedule or {"n": sc["race_n"], "delay_ms": 30}; rep = {}
    csc = {**sc, "base_url": f"http://127.0.0.1:{sc['candidate_port']}"}
    with server(sc, code, cfg=cfg) as cl:
        rep["regression_failures"] = regression_custom(cfg, sc, csc, cl) if sc.get("custom") else regression(cl, csc)
        if rep["regression_failures"]:
            return False, rep, "Sequential regression tests failed: " + "; ".join(rep["regression_failures"])
        f, names = trials(cfg, csc, cl, invariants, 1, schedule["delay_ms"])
        rep["replay"] = {"trials": 1, "violations": f, "invariants": names}
        if f: return False, rep, f"Replaying the original failing schedule still violates {names}. The race is not fixed."
        rep["fresh_trials"] = []
        for d in (0, 30):
            f, names = trials(cfg, csc, cl, invariants, k, d)
            rep["fresh_trials"].append({"delay_ms": d, "trials": k, "violations": f, "invariants": names})
            if f: return False, rep, f"Your patch still violates {names} in {f} of {k} fresh trials with a {d} ms pause. The race is not fixed."
        if sc.get("throughput"): rep["throughput_rps"] = throughput(csc, cl)
    return True, rep, ""
