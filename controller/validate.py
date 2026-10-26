"""Validate a candidate fix: run it as a COPY of the app (never the original), then regression cases, replay of the failing
schedule, K fresh trials at two delays, and throughput. LLM-written code never sees our API keys.
Convention: each endpoint function in the app file starts at its decorator and ends at a line `# END-ENDPOINT`."""
import os, re, sys, time, threading, subprocess, contextlib, httpx
from . import config, attacker

MARK = "# END-ENDPOINT"

def decorator_re(ep):
    """matches @app.post("/path") with either quote style (ast.unparse turns " into ')"""
    return re.compile(r"@app\." + ep["method"].lower() + r"\(\s*[\"']" + re.escape(ep["path"]) + r"[\"']\s*\)")

def region(src, ep):
    """(start, end) character offsets of the endpoint function: decorator .. end marker (or next @app decorator)"""
    m0 = decorator_re(ep).search(src)
    if not m0: raise ValueError(f"no @app.{ep['method'].lower()}({ep['path']!r}) decorator found in the app file")
    start = m0.start()
    m = src.find(MARK, start)
    if m != -1: return start, m
    n = re.search(r"^@app\.", src[start + 1:], re.M)
    return start, (start + 1 + n.start()) if n else len(src)

def patched_source(src, ep, code):
    a, b = region(src, ep)
    return src[:a] + code.strip() + "\n" + src[b:]

@contextlib.contextmanager
def server(sc, code=None, name="candidate_app"):
    """run a copy of the app with the endpoint function replaced by `code` (None = unchanged), MODE=vuln, on candidate_port"""
    out = config.ROOT / "runs" / "repair"; out.mkdir(parents=True, exist_ok=True)
    src = config.app_path(sc).read_text(encoding="utf-8")
    (out / f"{name}.py").write_text(patched_source(src, sc["endpoint"], code) if code else src, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if "API_KEY" not in k.upper()}; env["MODE"] = "vuln"
    port = sc["candidate_port"]
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", f"{name}:app", "--port", str(port), "--log-level", "warning"],
                         cwd=out, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cl = attacker.client(f"http://127.0.0.1:{port}")
    try:
        for _ in range(80):
            try:
                if cl.get("/openapi.json").status_code == 200: break
            except httpx.HTTPError: time.sleep(0.25)
        else: raise RuntimeError("candidate app did not start (check the code compiles and GH_DATABASE_URL is set)")
        yield cl
    finally:
        cl.close(); p.terminate()
        try: p.wait(10)
        except subprocess.TimeoutExpired: p.kill()

def regression(cl, sc):
    """sequential behaviour must be unchanged. Cases come from the config. Returns failure messages."""
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

def trials(cfg, sc, cl, invariants, k, delay):
    """k fresh barrier trials on the candidate; returns (trials_with_violation, names of violated invariants)"""
    admin, ro = attacker.connect(cfg), attacker.connect(cfg, True); fails, names = 0, set()
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
    with server(sc, code) as cl:
        rep["regression_failures"] = regression(cl, csc)
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
        rep["throughput_rps"] = throughput(csc, cl)
    return True, rep, ""
