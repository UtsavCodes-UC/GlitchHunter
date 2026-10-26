"""Propose step: ask the LLM for invariants, then validate each SQL against the real database (read-only, timeout)."""
import re, json
from controller import config, attacker
from . import llm, context

TEMPLATE = config.ROOT / "orchestrator" / "prompts" / "invariants_v2_template.txt"

def parse(raw):
    m = re.search(r"\{.*\}", raw, re.S)
    try: return json.loads(m.group(0))["invariants"] if m else None
    except (ValueError, KeyError, TypeError): return None

def validate_sql(ro, sql):
    """(ok, error): a single SELECT/WITH only, then executed read-only against the real schema"""
    s = sql.strip().rstrip(";")
    if ";" in s or not re.match(r"(?is)^\s*(select|with)\b", s): return False, "not a single SELECT"
    if re.search(r"%s|\{|\}", s): return False, "placeholder in SQL"
    try:
        with ro.cursor() as cur: cur.execute(s); cur.fetchall()
        return True, None
    except Exception as e: return False, str(e).strip().splitlines()[0]

def propose(cfg, sc, samples=3):
    """returns (invariants in the contract shape, stats). Needs the app running (tables are read from the live database)."""
    admin, ro, cl = attacker.connect(cfg), attacker.connect(cfg, True), attacker.client(sc["base_url"])
    try:
        attacker.prepare(cl, admin, sc)  # make sure tables, ops_log and initial_state exist so the schema text is complete
        prompt = TEMPLATE.read_text(encoding="utf-8").replace("{APP}", context.app_text(cfg, sc))
        out, seen, total, valid, parse_fail = [], set(), 0, 0, 0
        for k in range(samples):
            invs = parse(llm.complete(prompt))
            if invs is None: parse_fail += 1; continue
            for inv in invs:
                sql = inv.get("sql", ""); ok, err = validate_sql(ro, sql); total += 1; valid += ok
                key = " ".join(sql.lower().split())
                if not ok or key in seen: continue
                seen.add(key); slug = re.sub(r"\W+", "_", inv.get("name", "invariant").strip().lower()).strip("_") or "invariant"
                iid, n = f"{sc['name']}.{slug}", 2
                while any(o["id"] == iid for o in out): iid = f"{sc['name']}.{slug}_{n}"; n += 1
                out.append({"id": iid, "name": slug, "english": inv.get("english", ""), "sql": sql.strip().rstrip(";"),
                            "source": "llm", "status": "proposed", "stats": {}})
    finally: cl.close(); admin.close(); ro.close()
    return out, {"provider": llm.PROVIDER, "model": llm.LAST_MODEL, "samples": samples, "proposed": total, "valid_sql": valid,
                 "unique_valid": len(out), "parse_failures": parse_fail}
