"""Ask the LLM for invariants for one app, then validate each SQL against the real database.
usage: python propose_invariants.py APP [SAMPLES=3]      APP = wallet | inventory | coupon
Needs the rh tables to exist (run the demo app's /reset once). Output: runs/proposals/<provider>_<app>.json"""
import sys, re, json, pathlib, psycopg2
import llm, controller as c

ROOT = pathlib.Path(__file__).resolve().parent.parent

def parse(raw):
    m = re.search(r"\{.*\}", raw, re.S)
    try: return json.loads(m.group(0))["invariants"] if m else None
    except (ValueError, KeyError, TypeError): return None

def validate(conn, sql):
    """returns (ok, error): single SELECT/WITH only, then executed read-only with a timeout against the real schema"""
    s = sql.strip().rstrip(";")
    if ";" in s or not re.match(r"(?is)^\s*(select|with)\b", s): return False, "not a single SELECT"
    if re.search(r"%s|\{|\}", s): return False, "placeholder in SQL"
    try:
        with conn.cursor() as cur: cur.execute(s); cur.fetchall()
        return True, None
    except Exception as e:
        return False, str(e).strip().splitlines()[0]

if __name__ == "__main__":
    app = sys.argv[1]; samples = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    prompt = (ROOT / "prompts" / "invariants_v2_template.txt").read_text(encoding="utf-8").replace(
        "{APP}", (ROOT / "prompts" / f"app_text_{app}.txt").read_text(encoding="utf-8"))
    conn = psycopg2.connect(c.DSN); conn.set_session(readonly=True, autocommit=True)
    conn.cursor().execute("set statement_timeout = 5000")
    out, total, valid = [], 0, 0
    for k in range(samples):
        raw = llm.complete(prompt); invs = parse(raw)
        if invs is None: out.append({"sample": k, "parse_error": True, "raw": raw}); print(f"sample {k}: JSON did not parse"); continue
        for inv in invs:
            ok, err = validate(conn, inv.get("sql", "")); total += 1; valid += ok
            out.append({"sample": k, **inv, "valid_sql": ok, "error": err})
            print(f"sample {k} {inv.get('name','?'):28s} {'OK ' if ok else 'BAD'} {err or ''}")
    d = ROOT / "runs" / "proposals"; d.mkdir(parents=True, exist_ok=True)
    (d / f"{llm.PROVIDER}_{app}.json").write_text(json.dumps({"provider": llm.PROVIDER, "model": llm.MODEL, "app": app, "invariants": out}, indent=2))
    print(f"{llm.PROVIDER}/{llm.MODEL} {app}: {valid}/{total} invariants have valid SQL")
