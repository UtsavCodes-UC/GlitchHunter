"""Understand an uploaded FastAPI app from what it ACTUALLY serves (the inspector's routes + OpenAPI document), not from guessing at
source files: routers and prefixes are already resolved, JSON body schemas and auth requirements are described, and every route
carries the file and line of its handler. Also finds the code related to an endpoint (called helpers, ORM models) for the AI."""
import ast, pathlib, re, textwrap

SKIP_DIRS = {"venv", ".venv", "site-packages", "__pycache__", "node_modules", ".git", "tests", "test", "alembic", "migrations"}
AUTH_HEADERS = ("authorization", "x-api-key", "api-key", "x-token", "token", "x-auth-token", "x-access-token")
QTY_NAMES = ("qty", "quantity", "amount", "count", "units", "seats", "points", "credits", "delta", "number", "value")
STATE_NAMES = ("stock", "quantity", "qty", "balance", "inventory", "available", "remaining", "credits", "points", "seats", "count", "amount", "units", "left")
NUMERIC = ("integer", "bigint", "smallint", "numeric", "real", "double precision", "decimal")

# ------------------------------------------------------------------ sample values from JSON schema
def _ref(schema, comps, depth=0):
    while isinstance(schema, dict) and "$ref" in schema and depth < 8:
        schema = comps.get("schemas", {}).get(schema["$ref"].rsplit("/", 1)[-1], {}); depth += 1
    return schema if isinstance(schema, dict) else {}

def sample_value(schema, comps, name="", depth=0):
    s = _ref(schema, comps)
    if depth > 6: return None
    for key in ("example", "default", "const"):
        if s.get(key) is not None: return s[key]
    if s.get("enum"): return s["enum"][0]
    for key in ("anyOf", "oneOf"):
        if key in s:
            for v in s[key]:
                if _ref(v, comps).get("type") != "null": return sample_value(v, comps, name, depth + 1)
            return None
    if s.get("allOf"):
        merged = {"properties": {}, "required": []}
        for v in s["allOf"]:
            r = _ref(v, comps); merged["properties"].update(r.get("properties", {})); merged["required"] += r.get("required", [])
        return sample_value({"type": "object", **merged}, comps, name, depth + 1)
    t = s.get("type")
    if t in ("integer", "number"):
        v = 1
        if s.get("minimum") is not None: v = max(v, int(s["minimum"]))
        if s.get("exclusiveMinimum") is not None and not isinstance(s["exclusiveMinimum"], bool): v = max(v, int(s["exclusiveMinimum"]) + 1)
        if s.get("maximum") is not None: v = min(v, int(s["maximum"]))
        return float(v) if t == "number" else v
    if t == "boolean": return True
    if t == "string":
        fmt, n = s.get("format", ""), name.lower()
        if fmt == "email" or "email" in n: return "user@example.com"
        if fmt == "date-time": return "2024-01-01T00:00:00Z"
        if fmt == "date": return "2024-01-01"
        if fmt == "uuid": return "00000000-0000-0000-0000-000000000001"
        if fmt in ("uri", "url"): return "https://example.com"
        if "password" in n: return "Passw0rd!"
        return "test"
    if t == "array":
        item = sample_value(s.get("items", {}), comps, name, depth + 1)
        return [] if item is None else [item]
    if t == "object" or "properties" in s:
        props, req = s.get("properties", {}), s.get("required", [])
        return {k: sample_value(props[k], comps, k, depth + 1) for k in (req or list(props)) if k in props}
    return None

# ------------------------------------------------------------------ endpoint list
def _func_text(file, lineno, name):
    """source of the handler function incl. decorators, from its file (None if it cannot be read)"""
    try: text = pathlib.Path(file).read_text(encoding="utf-8-sig"); tree = ast.parse(text)
    except (OSError, SyntaxError, UnicodeDecodeError): return None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            first = min([d.lineno for d in n.decorator_list] + [n.lineno])
            if first == lineno or n.lineno == lineno or abs(first - lineno) <= 1:
                return "\n".join(text.splitlines()[first - 1:n.end_lineno])
    return None

# ------------------------------------------------------------------ code related to an endpoint
_BUILTINS = {"print", "len", "int", "str", "float", "bool", "dict", "list", "set", "tuple", "range", "isinstance", "sum", "min", "max", "sorted", "enumerate", "zip", "any", "all", "map", "filter", "getattr", "setattr", "HTTPException", "Depends", "Query", "Header", "Body", "Path"}
_COMMON = {"get", "add", "commit", "query", "filter", "first", "all", "append", "format", "update", "delete", "execute", "scalar", "scalars", "one", "refresh", "flush", "rollback", "close", "items", "keys", "values", "join", "dict", "json", "copy"}

def _index(src_dir):
    funcs, classes = {}, {}
    for p in pathlib.Path(src_dir).rglob("*.py"):
        rel = p.relative_to(src_dir)
        if set(rel.parts[:-1]) & SKIP_DIRS: continue
        try: text = p.read_text(encoding="utf-8-sig"); tree = ast.parse(text)   # utf-8-sig: Windows editors often add a BOM
        except (OSError, SyntaxError, UnicodeDecodeError): continue
        for n in ast.walk(tree):
            seg = ast.get_source_segment(text, n) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else None
            if not seg: continue
            (classes if isinstance(n, ast.ClassDef) else funcs).setdefault(n.name, []).append((rel.as_posix(), seg, n))
    return funcs, classes

def related_code(src_dir, code_text, own_name="", limit=9000, depth=2, index=None):
    """source of the helper functions an endpoint calls (up to `depth` levels) and of the ORM/model classes it mentions.
    `index` = a precomputed _index(src_dir) (the static scan reuses one for every route)"""
    if not code_text: return ""
    funcs, classes = index or _index(src_dir); out, seen, total = [], {own_name}, 0
    def names_in(text):
        try: tree = ast.parse(textwrap.dedent(text))
        except SyntaxError: return [], []
        calls, loads = [], []
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                f = n.func; nm = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                if nm and nm not in _BUILTINS: calls.append(nm)
            elif isinstance(n, ast.Name): loads.append(n.id)
        return calls, loads
    frontier = [code_text]
    for _ in range(depth):
        nxt = []
        for text in frontier:
            calls, loads = names_in(text)
            for nm in dict.fromkeys(calls):
                if nm in seen or nm in _COMMON or nm not in funcs or len(funcs[nm]) > 3: continue
                seen.add(nm)
                for rel, seg, _n in funcs[nm]:
                    if total + len(seg) > limit: return "\n\n".join(out)
                    out.append(f"# {rel}\n{seg}"); total += len(seg); nxt.append(seg)
            for nm in dict.fromkeys(loads):
                if nm in seen or nm not in classes or len(classes[nm]) > 2: continue
                for rel, seg, node in classes[nm]:
                    if len(seg) > 3000 or not ("__tablename__" in seg or any(getattr(b, "id", getattr(b, "attr", "")) in ("Base", "DeclarativeBase", "SQLModel", "BaseModel", "Model") for b in node.bases)): continue
                    seen.add(nm)
                    if total + len(seg) > limit: return "\n\n".join(out)
                    out.append(f"# {rel}\n{seg}"); total += len(seg)
        frontier = nxt
    return "\n\n".join(out)
