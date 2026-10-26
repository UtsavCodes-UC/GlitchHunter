"""Repair step: the LLM proposes a fixed endpoint function; it is accepted only if controller.validate accepts it.
Failed attempts feed their reason back into the next prompt (up to max_attempts)."""
import re, ast, json
from controller import attacker, validate
from . import llm, context

PROMPT = """You are fixing a race condition in a FastAPI + PostgreSQL endpoint.

EVIDENCE (a failing run, reproduced): {evidence}
Violated invariants (each SQL returns a row when violated): {inv}

CURRENT CODE:
{code}
{names}

Fix it with ONE of: an atomic conditional UPDATE ... RETURNING, SELECT ... FOR UPDATE, an INSERT ... ON CONFLICT with a unique constraint, or a PostgreSQL advisory lock.
RULES: keep the decorator and the exact signature `{signature}`{pause}.
Keep behaviour: same responses and status codes as the current code, and keep the way the function commits its transaction. Define no other function, use no imports.
{feedback}
Respond with ONLY this JSON: {{"strategy": "...", "explanation": "...", "code": "<the complete function including the decorator>"}}"""

DEMO_NAMES = "Names already available in the module (do NOT import anything): app, Conn (context manager giving a psycopg2 connection), hook(ms), Header, HTTPException."
DEMO_PAUSE = " (a test-only pause parameter may be ignored if your fix has no gap to pause in)"
CUSTOM_NAMES = ("THE WHOLE FILE the function lives in (context only; it already imports what it needs, so you may use any name it defines or imports "
                "but must add NO imports; return only the one function):\n{file}")

def static_check(code, sc):
    if re.search(r"\bimport\b|\bexec\b|\beval\b|\bopen\s*\(|__|subprocess|\bos\.|\bsys\.", code): return "forbidden construct"
    try: tree = ast.parse(code)
    except SyntaxError as e: return f"syntax error: {e}"
    if len(tree.body) != 1 or not isinstance(tree.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)): return "must be exactly one function"
    if not validate.decorator_re(sc["endpoint"]).search(code): return "decorator missing or changed"
    return None

def find_failing_run(cfg, sc, invariants, tries=None, delay=30):
    """reproduce the bug on the real (vulnerable) app to use as evidence; returns the failing trial or None.
    Uploaded apps have no test pause, so the race is rarer and more tries are needed."""
    tries = tries or (80 if sc.get("custom") else 8)
    admin, ro, cl = attacker.connect(cfg, sc=sc), attacker.connect(cfg, True, sc), attacker.client(sc["base_url"])
    try:
        for _ in range(tries):
            t = attacker.trial(cl, admin, ro, sc, invariants, sc["race_n"], delay)
            if attacker.fired(t["violations"]): return t
    finally: cl.close(); admin.close(); ro.close()
    return None

def repair(cfg, sc, invariants, k=50, max_attempts=3, failing=None):
    """invariants = {id: sql}. Returns {"attempts": [...], "accepted": bool, "negative_control": {...}, "evidence": trial}"""
    failing = failing or find_failing_run(cfg, sc, invariants)
    if failing is None: raise RuntimeError("could not reproduce a failing run on the app; is it running in MODE=vuln?" if not sc.get("custom")
                                           else "could not reproduce a failing run on your app with the approved checks (try more simultaneous requests or different checks)")
    code, signature = context.vuln_function(sc); ep = sc["endpoint"]
    names, pause = (CUSTOM_NAMES.format(file=context.file_context(sc)), "") if sc.get("custom") else (DEMO_NAMES, DEMO_PAUSE)
    evidence = (f"initial state {failing['initial_state']}; {failing['n']} simultaneous requests {ep['method']} {ep['path']} "
                f"params {ep['params']}; response statuses {[r['status'] for r in failing['requests']]}; final state {failing['final_state']}.")
    inv_text = json.dumps({i: " ".join(invariants[i].split()) for i in attacker.fired(failing["violations"])})
    attempts, feedback, accepted = [], "", False
    for n in range(1, max_attempts + 1):
        prompt = PROMPT.format(evidence=evidence, inv=inv_text, code=code, names=names, signature=signature, pause=pause, feedback=feedback)
        entry = {"attempt": n, "accepted": False}
        try: raw = llm.complete(prompt, max_tokens=1500)
        except Exception as e:  # rate limit / network: record it as a failed attempt instead of crashing the run
            entry["reason"] = f"LLM call failed: {e!r}"; attempts.append(entry); continue
        entry["model"] = llm.LAST_MODEL
        try:
            p = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
            entry.update(strategy=p.get("strategy", ""), explanation=p.get("explanation", ""),
                         patch={"file": sc["app_file"], "function": ep["path"], "code": p["code"]})
        except Exception as e:
            entry["reason"] = f"unparseable reply: {e!r}"; feedback = "Your previous reply was not valid JSON with a 'code' field."
            attempts.append(entry); continue
        err = static_check(entry["patch"]["code"], sc)
        if err: entry["reason"] = "static check: " + err; feedback = f"Your previous code was rejected: {err}."
        else:
            ok, rep, fb = validate.validate_candidate(cfg, sc, entry["patch"]["code"], invariants, k)
            entry.update(validation=rep, accepted=ok, reason=fb); feedback = f"Previous attempt feedback: {fb}" if fb else ""; accepted = ok
        attempts.append(entry)
        if accepted: break
    return {"attempts": attempts, "accepted": accepted, "negative_control": negative_control(cfg, sc, invariants, code),
            "evidence": failing}

def negative_control(cfg, sc, invariants, vuln_code):
    """the ORIGINAL buggy code must be rejected by the same validation, otherwise an 'accepted' verdict means nothing"""
    ok, rep, fb = validate.validate_candidate(cfg, sc, vuln_code, invariants, k=10)
    return {"buggy_code_accepted": ok, "validator_working": not ok, "reason": fb}
