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
    try: text = pathlib.Path(file).read_text(encoding="utf-8"); tree = ast.parse(text)
    except (OSError, SyntaxError, UnicodeDecodeError): return None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            first = min([d.lineno for d in n.decorator_list] + [n.lineno])
            if first == lineno or n.lineno == lineno or abs(first - lineno) <= 1:
                return "\n".join(text.splitlines()[first - 1:n.end_lineno])
    return None

def classify(text):
    low = (text or "").lower()
    writes = bool(re.search(r"\.commit\(|\.add\(|\.add_all\(|\.merge\(|\.delete\(|\.flush\(|\bupdate\(|\binsert\(|insert\s+into|update\s+\w+\s+set|delete\s+from|\bsetattr\(|\s[-+]=\s", low))
    reads = bool(re.search(r"\.query\(|\bselect\b|\.first\(|\.one\(|\.one_or_none\(|\.scalars?\(|\.all\(|\.filter|\.get\(|\.execute\(", low))
    if writes and reads: return "reads, then writes to the database (the classic race pattern)"
    if writes: return "writes to the database"
    if reads: return "only reads from the database"
    return "no database access seen in this function or the helpers it calls"

def endpoints(info, src_dir):
    """info = the inspector's JSON. Returns the endpoint options for the upload page, best candidates first."""
    api = info["openapi"]; comps = api.get("components", {}); schemes = comps.get("securitySchemes", {}); src_dir = pathlib.Path(src_dir).resolve()
    out = []
    for r in info["routes"]:
        for method in r["methods"]:
            op = api.get("paths", {}).get(r["path"], {}).get(method.lower())
            if op is None: continue  # not part of the public schema
            query, path_p, headers, blockers, notes, auth = {}, {}, {}, [], [], None
            for prm in op.get("parameters", []):
                where, nm = prm.get("in"), prm["name"]; val = sample_value(prm.get("schema", {}), comps, nm)
                if where == "path": path_p[nm] = 1 if val is None else val
                elif where == "query" and prm.get("required"): query[nm] = "test" if val is None else val
                elif where == "header" and prm.get("required"):
                    if nm.lower() in AUTH_HEADERS: auth = {"kind": "header", "header": nm, "prefix": ""}
                    else: headers[nm] = "" if val is None else str(val)
                elif where == "cookie" and prm.get("required"): blockers.append(f"needs the cookie '{nm}' (cookies are not supported yet)")
            body = None; rb = op.get("requestBody")
            if rb:
                content = rb.get("content", {})
                if "application/json" in content: body = sample_value(content["application/json"].get("schema", {}), comps)
                else: blockers.append(f"takes a {next(iter(content), 'special')} body (a form or file upload): not supported yet")
            if auth is None:
                for req in (op.get("security", api.get("security")) or []):
                    for sname in req:
                        sc = schemes.get(sname, {}); typ = sc.get("type")
                        if typ == "http" and sc.get("scheme", "").lower() == "basic": auth = {"kind": "basic", "header": "Authorization", "prefix": "Basic "}
                        elif typ in ("http", "oauth2", "openIdConnect"): auth = {"kind": "bearer", "header": "Authorization", "prefix": "Bearer "}
                        elif typ == "apiKey" and sc.get("in") == "header": auth = {"kind": "header", "header": sc["name"], "prefix": ""}
                        elif typ == "apiKey" and sc.get("in") == "query": blockers.append("needs an API key in the query string (not supported yet)")
                        elif typ == "apiKey": blockers.append("needs a cookie-based login (not supported yet)")
                        if auth: break
                    if auth: break
            if auth: notes.append(f"requires login: you will be asked for the {auth['header']} header value")
            if headers: notes.append("needs header(s): " + ", ".join(headers))
            f = pathlib.Path(r["file"]).resolve() if r["file"] else None
            inside = bool(f) and (src_dir == f or src_dir in f.parents)
            if not inside: blockers.append("its code lives in an installed library, not in your project, so the AI cannot read it")
            text = _func_text(r["file"], r["lineno"], r["func"]) if inside else None
            hint_text = (text or "") + "\n" + (related_code(src_dir, text, r["func"]) if text else "")
            flat = {**path_p, **query, **(body if isinstance(body, dict) else {})}
            out.append({"method": method, "path": r["path"], "function": r["func"], "file": f.relative_to(src_dir).as_posix() if inside else "", "lineno": r["lineno"],
                        "is_async": r["is_async"], "supported": not blockers, "unsupported_reasons": blockers, "notes": notes, "auth": auth,
                        "required_headers": headers, "sample_params": query, "sample_path_params": path_p, "sample_json": body,
                        "qty_candidates": [k for k in flat if isinstance(flat[k], (int, float)) and not isinstance(flat[k], bool)],
                        "suggested_qty": next((k for q in QTY_NAMES for k in flat if k.lower() == q and isinstance(flat[k], (int, float))), None),
                        "hint": classify(hint_text) if text else "its code could not be read"})
    rank = lambda e: (not e["supported"], 0 if "classic" in e["hint"] else 1 if e["hint"].startswith("writes") else 2, e["method"] == "GET")
    return sorted(out, key=rank)

# ------------------------------------------------------------------ choosing the number to watch
def suggest_state(columns, related=""):
    """columns = {table: [{"name", "type"}]}. Pick the numeric column most likely to be the 'stock / balance / count' the endpoint changes."""
    best, score = None, -1
    low = related.lower()
    for table, cols in columns.items():
        for c in cols:
            if c["type"] not in NUMERIC: continue
            n = c["name"].lower()
            if n == "id" or n.endswith("_id"): continue
            changed = re.search(rf"\.{re.escape(n)}\s*[-+*/]?=(?!=)|\b{re.escape(n)}\s*=\s*\w+\.{re.escape(n)}\s*[-+]|set\s+{re.escape(n)}\s*=", low)  # the code assigns / decrements it
            s = (3 if any(n == k or n.endswith("_" + k) or n.startswith(k + "_") for k in STATE_NAMES) else 0) + (2 if table.lower().rstrip("s") in low else 0) + (1 if n in low else 0) + (4 if changed else 0)
            if s > score: best, score = {"table": table, "column": c["name"]}, s
    return best

# ------------------------------------------------------------------ code related to an endpoint
_BUILTINS = {"print", "len", "int", "str", "float", "bool", "dict", "list", "set", "tuple", "range", "isinstance", "sum", "min", "max", "sorted", "enumerate", "zip", "any", "all", "map", "filter", "getattr", "setattr", "HTTPException", "Depends", "Query", "Header", "Body", "Path"}
_COMMON = {"get", "add", "commit", "query", "filter", "first", "all", "append", "format", "update", "delete", "execute", "scalar", "scalars", "one", "refresh", "flush", "rollback", "close", "items", "keys", "values", "join", "dict", "json", "copy"}

def _index(src_dir):
    funcs, classes = {}, {}
    for p in pathlib.Path(src_dir).rglob("*.py"):
        rel = p.relative_to(src_dir)
        if set(rel.parts[:-1]) & SKIP_DIRS: continue
        try: text = p.read_text(encoding="utf-8"); tree = ast.parse(text)
        except (OSError, SyntaxError, UnicodeDecodeError): continue
        for n in ast.walk(tree):
            seg = ast.get_source_segment(text, n) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else None
            if not seg: continue
            (classes if isinstance(n, ast.ClassDef) else funcs).setdefault(n.name, []).append((rel.as_posix(), seg, n))
    return funcs, classes

def related_code(src_dir, code_text, own_name="", limit=9000, depth=2):
    """source of the helper functions an endpoint calls (up to `depth` levels) and of the ORM/model classes it mentions"""
    if not code_text: return ""
    funcs, classes = _index(src_dir); out, seen, total = [], {own_name}, 0
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
