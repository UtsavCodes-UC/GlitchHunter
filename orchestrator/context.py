"""What the LLM sees about a scenario: the endpoint code (vulnerable branch only) and the live table schema.
The app file holds both MODE branches in one function; showing the fixed branch would hand over the repair, so it is stripped."""
import ast, pathlib
from controller import config, attacker, validate

class _VulnOnly(ast.NodeTransformer):
    def visit_If(self, node):
        self.generic_visit(node)
        t = node.test
        if isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == "MODE" and len(t.comparators) == 1 \
                and isinstance(t.comparators[0], ast.Constant) and isinstance(t.ops[0], ast.Eq):
            if t.comparators[0].value == "vuln": return node.body
            if t.comparators[0].value == "fixed": return node.orelse or None
        return node

def vuln_function(sc):
    """(source text of the vulnerable endpoint function incl. decorator, its `def` line)"""
    src = config.app_path(sc).read_text(encoding="utf-8"); a, b = validate.region(src, sc["endpoint"])
    tree = _VulnOnly().visit(ast.parse(src[a:b])); ast.fix_missing_locations(tree)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    return ast.unparse(tree), f"def {fn.name}({ast.unparse(fn.args)})"

def schema_text(cfg, sc):
    """CREATE TABLE text read from the live database (so the LLM sees exactly what is stored)"""
    admin = attacker.connect(cfg); lines = []
    try:
        with admin.cursor() as cur:
            for t in sc["tables"]:
                cur.execute("select column_name, data_type from information_schema.columns where table_schema = current_schema() "
                            "and table_name = %s order by ordinal_position", (t,))
                cols = ", ".join(f"{c} {d}" for c, d in cur.fetchall())
                if cols: lines.append(f"CREATE TABLE {t}({cols});")
    finally: admin.close()
    return "\n".join(lines)

def app_text(cfg, sc):
    code, _ = vuln_function(sc)
    return (f"Schema:\n{schema_text(cfg, sc)}\nCode:\n{code}\n"
            f"In ops_log, the endpoint column holds the request path WITH a leading slash: '{sc['endpoint']['path']}'.")
