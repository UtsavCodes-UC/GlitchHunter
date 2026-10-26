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

def region_func(src, func):
    """(start, end) offsets of a handler found by file position (uploaded apps): its first decorator line .. the end of its last line"""
    import ast
    tree = ast.parse(src); lines = src.splitlines(keepends=True)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func["name"]:
            first = min([d.lineno for d in n.decorator_list] + [n.lineno])
            if abs(first - func["lineno"]) <= 1 or n.lineno == func["lineno"]:
                return sum(map(len, lines[:first - 1])), sum(map(len, lines[:n.end_lineno]))
    raise ValueError(f"could not find the function {func['name']} in the file (was it changed after upload?)")

def endpoint_region(src, sc):
    return region_func(src, sc["func"]) if sc.get("func") else region(src, sc["endpoint"])

def patched_source(src, sc, code):
    a, b = endpoint_region(src, sc)
    return src[:a] + code.strip("\n") + ("\n" if sc.get("func") else "\n\n") + src[b:]

def same_decorators(sc, code):
    """a fix for an uploaded app must keep the handler's decorators (they define its route and its dependencies)"""
    import ast
    src = config.app_path(sc).read_text(encoding="utf-8-sig"); a, b = endpoint_region(src, sc)
    orig = ast.parse(src[a:b]).body[0]; new = ast.parse(code).body[0]
    return [ast.unparse(d) for d in orig.decorator_list] == [ast.unparse(d) for d in new.decorator_list]

def _env(cfg, sc):
    env = config.test_env(os.environ, sc, cfg); env["MODE"] = "vuln"
    return env

@contextlib.contextmanager
def server(sc, code=None, name="candidate_app", cfg=None):
    """run a copy of the app with the endpoint function replaced by `code` (None = unchanged) on candidate_port"""
    out = config.ROOT / "runs" / "repair"; out.mkdir(parents=True, exist_ok=True); port = sc["candidate_port"]
    if sc.get("custom"):   # same isolation as the original app: fresh temp copy of the files (fix applied), minimal environment, own database role
        from . import sandbox
        work = sandbox.fresh_copy(sc["project_dir"], sc["project_id"] + "_cand")
        target = work / "app" / pathlib.Path(sc["app_file"]).relative_to(pathlib.Path(sc["project_dir"])); text = target.read_text(encoding="utf-8-sig")
        if code: target.write_text(patched_source(text, sc, code), encoding="utf-8")
        logpath = out / f"{name}.log"; p = sandbox.start(cfg, sc, work, sc["app"], port, logpath)
        cl = attacker.client(f"http://127.0.0.1:{port}")
        try:
            try: sandbox.wait_ready(p, f"http://127.0.0.1:{port}", logpath)
            except RuntimeError as e: raise RuntimeError("candidate " + str(e))
            yield cl
        finally: cl.close(); sandbox.kill(p); sandbox.cleanup(work)
        return
    src = config.app_path(sc).read_text(encoding="utf-8-sig")
    (out / f"{name}.py").write_text(patched_source(src, sc, code) if code else src, encoding="utf-8")
    log = open(out / f"{name}.log", "wb")
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", f"{name}:app", "--port", str(port), "--log-level", "warning"],
                         cwd=out, env=_env(cfg, sc), stdout=log, stderr=log)
    cl = attacker.client(f"http://127.0.0.1:{port}")
    try:
        ready = False
        for _ in range(80):
            if p.poll() is not None: break
            try:
                cl.get("/openapi.json"); ready = True; break   # any HTTP answer (even 404 when docs are switched off) means it is up
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
    """uploaded apps: everyday behaviour = how the ORIGINAL app behaves one request at a time (statuses and every table afterwards).
    Differential: the original is run twice, and columns that differ between those two identical runs (timestamps, random ids) are ignored."""
    ref_cl = attacker.client(sc["base_url"])
    try: ref, ref2 = attacker.sequential_signature(cfg, sc, ref_cl), attacker.sequential_signature(cfg, sc, ref_cl)
    finally: ref_cl.close()
    vol = attacker.volatile_columns(ref, ref2); got = attacker.sequential_signature(cfg, csc, cl)
    if got["statuses"] != ref["statuses"]:
        return [f"one request at a time, the original returned {ref['statuses']} but the fix returned {got['statuses']}"]
    a, b = attacker.masked_tables(ref, vol), attacker.masked_tables(got, vol)
    for t in sorted(set(a) | set(b)):
        if a.get(t) != b.get(t):
            return [f"after the same requests one at a time, the table {t} differs: the original left {len(a.get(t, []))} row(s) {a.get(t, [])[:2]}, "
                    f"the fix left {len(b.get(t, []))} row(s) {b.get(t, [])[:2]}"]
    return []

def app_error_tail(name="candidate_app", n=2):
    """the last error lines the test copy of the app printed (for example a NameError behind an HTTP 500): the AI needs the cause, not just 'it returned 500'"""
    try: lines = (config.ROOT / "runs" / "repair" / f"{name}.log").read_text(errors="replace").splitlines()
    except OSError: return ""
    errs = [l.strip() for l in lines if re.search(r"\b\w*(Error|Exception)\b", l) and not l.strip().startswith(("File ", "raise ", "During"))]
    return " | ".join(errs[-n:])[:400]

def trials(cfg, sc, cl, invariants, k, delay):
    """k fresh barrier trials on the candidate; returns (trials_with_violation, names of violated invariants)"""
    admin, ro = attacker.connect(cfg, sc=sc), attacker.connect(cfg, True, sc); fails, names = 0, set()
    try:
        for _ in range(k):
            bad = attacker.fired(attacker.trial(cl, admin, ro, sc, invariants, sc["race_n"], delay)["violations"])
            fails += bool(bad); names.update(bad)
    finally: admin.close(); ro.close()
    return fails, sorted(names)

def throughput_custom(cfg, sc, cl, threads=8, per=15):
    """uploaded projects: requests per second when `threads` clients cycle through the burst's requests (state is reset once first; one quick measurement)"""
    admin = attacker.connect(cfg, sc=sc)
    try: attacker.prepare(cl, admin, sc)
    finally: admin.close()
    def w(k):
        for j in range(per):
            url, query, body, _ = attacker.request_parts(sc, k + j)
            try: cl.request(sc["endpoint"]["method"], url, params=query, json=body, headers=sc["endpoint"].get("headers") or None)
            except httpx.HTTPError: pass
    ts = [threading.Thread(target=w, args=(i,)) for i in range(threads)]; t0 = time.perf_counter()
    [t.start() for t in ts]; [t.join() for t in ts]
    return round(threads * per / (time.perf_counter() - t0), 1)

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
            hint = app_error_tail()
            return False, rep, "Sequential regression tests failed: " + "; ".join(rep["regression_failures"]) + (f" The test copy of the app printed this error: {hint}" if hint else "")
        f, names = trials(cfg, csc, cl, invariants, 1, schedule["delay_ms"])
        rep["replay"] = {"trials": 1, "violations": f, "invariants": names}
        if f: return False, rep, f"Replaying the original failing schedule still violates {names}. The race is not fixed."
        rep["fresh_trials"] = []
        for d in (0, 30):
            f, names = trials(cfg, csc, cl, invariants, k, d)
            rep["fresh_trials"].append({"delay_ms": d, "trials": k, "violations": f, "invariants": names})
            if f: return False, rep, f"Your patch still violates {names} in {f} of {k} fresh trials with a {d} ms pause. The race is not fixed."
        if sc.get("custom"): rep["throughput_rps"] = throughput_custom(cfg, csc, cl)
        elif sc.get("throughput"): rep["throughput_rps"] = throughput(csc, cl)
    return True, rep, ""
