"""What the LLM sees about a scenario: the endpoint code (vulnerable branch only) and the live table schema.
The demo app files hold both MODE branches in one function; showing the fixed branch would hand over the repair, so it is stripped.
Uploaded apps (sc["custom"]) have no MODE branches, so their code is shown as it is."""
import ast, json, re
from controller import config, attacker, validate

PROMPTS = config.ROOT / "orchestrator" / "prompts"

class _VulnOnly(ast.NodeTransformer):
    def visit_If(self, node):
        self.generic_visit(node)
        t = node.test
        if isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == "MODE" and len(t.comparators) == 1 \
                and isinstance(t.comparators[0], ast.Constant) and isinstance(t.ops[0], ast.Eq):
            if t.comparators[0].value == "vuln": return node.body
            if t.comparators[0].value == "fixed": return node.orelse or None
        return node

def template_for(sc):
    return PROMPTS / ("invariants_custom_template.txt" if sc.get("custom") else "invariants_v2_template.txt")

def vuln_function(sc):
    """(source text of the vulnerable endpoint function incl. decorators, its `def` line). Uploaded apps: the exact original text."""
    import textwrap
    src = config.app_path(sc).read_text(encoding="utf-8-sig"); a, b = validate.endpoint_region(src, sc)
    text = textwrap.dedent(src[a:b]) if sc.get("custom") else src[a:b]
    tree = ast.parse(text)
    fn = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    sig = f"{'async ' if isinstance(fn, ast.AsyncFunctionDef) else ''}def {fn.name}({ast.unparse(fn.args)})"
    if sc.get("custom"): return text.strip("\n"), sig
    tree = _VulnOnly().visit(tree); ast.fix_missing_locations(tree)
    return ast.unparse(tree), sig

def related(sc):
    """helper functions the endpoint calls and the model classes it uses (uploaded apps): where the real logic often lives"""
    from . import appscan
    code, _ = vuln_function(sc)
    return appscan.related_code(sc["project_dir"], code, (sc.get("func") or {}).get("name", ""))

def file_context(sc, limit=12000):
    """the whole endpoint file, so the LLM can see helper names and imports (uploaded apps only; truncated)"""
    return config.app_path(sc).read_text(encoding="utf-8-sig")[:limit]

def schema_text(cfg, sc):
    """CREATE TABLE text read from the live database (so the LLM sees exactly what is stored)"""
    admin = attacker.connect(cfg, sc=sc); lines = []
    try:
        with admin.cursor() as cur:
            for t in (attacker.app_tables(cur) if sc.get("custom") else sc["tables"]):
                cur.execute("select column_name, data_type from information_schema.columns where table_schema = current_schema() "
                            "and table_name = %s order by ordinal_position", (t,))
                cols = ", ".join(f"{c} {d}" for c, d in cur.fetchall())
                if cols: lines.append(f"CREATE TABLE {t}({cols});")
    finally: admin.close()
    return "\n".join(lines)

def app_text(cfg, sc):
    code, _ = vuln_function(sc)
    path = sc["endpoint"]["path"]
    if sc.get("custom"):
        schema = schema_text(cfg, sc); names = re.findall(r"CREATE TABLE (\w+)", schema); rel = related(sc); ep = sc["endpoint"]
        snaps = ", ".join(f"initial_{t}" for t in names)
        how = "in the query string" if ep.get("body") == "query" else "as a JSON body"
        return (f"Schema (the app's own tables; they hold the FINAL state after the run):\n{schema}\n"
                f"Before every run each table T is copied to initial_T ({snaps}), so initial_T holds the state BEFORE the run.\nCode:\n{code}\n"
                + (f"Related code the endpoint uses (helpers and models):\n{rel}\n" if rel else "")
                + f"Each try sends {len(sc['burst'])} requests at the same time: {ep['method']} {path}, one JSON object of values per request: {json.dumps(sc['burst'])[:800]}. "
                f"Values named like a {{placeholder}} in the path go in the address; the others are sent {how}. "
                f"In ops_log, the endpoint column holds the request path WITH a leading slash: '{path}'. "
                f"ALL the request's values (path values, query values and the JSON body's top-level fields) are in ops_log.params (jsonb), for example (params->>'quantity')::int.")
    return (f"Schema:\n{schema_text(cfg, sc)}\nCode:\n{code}\n"
            f"In ops_log, the endpoint column holds the request path WITH a leading slash: '{path}'.")
