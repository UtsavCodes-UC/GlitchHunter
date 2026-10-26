"""STATIC scan of an uploaded project: source text is parsed with `ast` and regular expressions ONLY. Nothing is imported or executed.
Finds the FastAPI apps and routers (with include_router prefixes), the routes with their parameters and request-body fields, a verdict
per route (a HINT from code patterns, never a proof), a guess of the database environment variable, and a guess of schema/seed SQL.
Limits: names are resolved by simple rules (same file, `from x import y`, `module.attr`); dynamic routing is not understood."""
import ast, re, pathlib
from . import appscan

METHODS = ("get", "post", "put", "patch", "delete")
GUARDS = [("SELECT ... FOR UPDATE", r"for\s+update|with_for_update\("), ("an advisory lock", r"pg_advisory|advisory_lock"),
          ("INSERT ... ON CONFLICT", r"on\s+conflict"), ("an atomic conditional UPDATE (UPDATE ... WHERE value >= amount)", r"update\s+[^;'\"]{0,200}?\bset\b[^;]{0,300}?\bwhere\b[^;]{0,300}?(>=|>|<=)"),
          ("a strict isolation level", r"serializable")]
STOCKY = ("stock", "quantity", "qty", "available", "seats", "remaining", "inventory", "units", "left", "count")
SQL_TYPES = {"Integer": "integer", "BigInteger": "bigint", "SmallInteger": "smallint", "String": "text", "Text": "text", "Boolean": "boolean", "Float": "double precision",
             "Numeric": "numeric", "DECIMAL": "numeric", "DateTime": "timestamp", "Date": "date", "JSON": "jsonb", "JSONB": "jsonb", "Uuid": "uuid", "UUID": "uuid"}
PY_TYPES = {"int": "integer", "str": "text", "float": "double precision", "bool": "boolean", "datetime": "timestamp", "date": "date", "Decimal": "numeric", "dict": "jsonb"}

def _s(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

def _name(node):
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None

def _join(*parts):
    p = "/".join(x.strip("/") for x in parts if x and x.strip("/"))
    return "/" + p

def _dflt(v):
    """(required, default constant) of a field/parameter default expression"""
    if v is None: return True, None
    if isinstance(v, ast.Call) and _name(v.func) in ("Field", "Query", "Body"):
        if v.args and isinstance(v.args[0], ast.Constant): v = v.args[0]
        else:
            d = next((k.value for k in v.keywords if k.arg == "default"), None)
            if d is None: return (not v.args), None
            v = d
    if isinstance(v, ast.Constant): return (v.value is ...), (None if v.value is ... else v.value)
    return False, None

def sample(ann, name=""):
    t = ast.unparse(ann) if ann is not None else "str"; n = name.lower()
    if t.startswith(("Optional[", "Union[")) or " | " in t: t = re.sub(r"Optional\[|\]|None|\|", " ", t).split()[0] if re.sub(r"Optional\[|\]|None|\|", " ", t).split() else "str"
    if t in ("int", "Decimal"): return 1
    if t == "float": return 1.0
    if t == "bool": return True
    if t.startswith(("list", "List")): return []
    if t.startswith(("dict", "Dict")): return {}
    if "email" in n: return "user@example.com"
    return "test"

class Project:
    def __init__(self, root):
        self.root = pathlib.Path(root); self.files = {}; self.trees = {}; self.text = {}
        for p in sorted(self.root.rglob("*.py")):
            rel = p.relative_to(self.root)
            if set(rel.parts[:-1]) & appscan.SKIP_DIRS: continue
            try: t = p.read_text(encoding="utf-8-sig"); self.trees[rel.as_posix()] = ast.parse(t); self.text[rel.as_posix()] = t
            except (SyntaxError, UnicodeDecodeError, ValueError): self.broken = getattr(self, "broken", []) + [rel.as_posix()]
        self.models = self._models()

    def dotted(self, rel):
        parts = list(pathlib.PurePosixPath(rel).with_suffix("").parts)
        return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)

    def module_of(self, rel):
        """the importable name of a file: relative to the first folder above its package chain (backend/app/main.py -> app.main)"""
        parts = pathlib.PurePosixPath(rel).parts; d = list(parts[:-1]); k = len(d)
        while k > 0 and f"{'/'.join(d[:k])}/__init__.py" in self.trees: k -= 1
        if k == len(d):   # no package folder: maybe a namespace package other files import as `from app.x import y`
            if d and any(re.search(rf"(^|\n)\s*(from|import)\s+{re.escape(d[-1])}[.\s]", t) for t in self.text.values()): k = len(d) - 1
            else: k = len(d)
        stem = pathlib.PurePosixPath(rel).stem
        return ".".join(d[k:] + ([] if stem == "__init__" else [stem]))

    def resolve(self, mod, frm):
        """file path of module `mod` as imported from file `frm` (relative dots or an absolute name matched by its tail)"""
        if mod.startswith("."):
            lvl = len(mod) - len(mod.lstrip(".")); base = list(pathlib.PurePosixPath(frm).parts[:-1])
            base = base[:len(base) - (lvl - 1)] if lvl > 1 else base; tail = mod.lstrip(".")
            cands = [("/".join(base + ([tail.replace(".", "/")] if tail else []))).strip("/")]
        else: cands = [mod.replace(".", "/")]
        for c in cands:
            for rel in self.trees:
                stem = rel[:-3] if rel.endswith(".py") else rel
                if rel.endswith("/__init__.py"): stem = rel[:-12]
                if stem == c or (not mod.startswith(".") and (stem.endswith("/" + c) or stem == c)): return rel
        return None

    def _models(self):
        """pydantic-style classes: name -> (bases, [(field, annotation, has_default)])"""
        out = {}
        for rel, tree in self.trees.items():
            for n in ast.walk(tree):
                if isinstance(n, ast.ClassDef):
                    fields = [(s.target.id, s.annotation, *_dflt(s.value)) for s in n.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)]
                    out[n.name] = ([_name(b) for b in n.bases], fields)
        return out

    def model_fields(self, name, seen=()):
        if name not in self.models or name in seen: return None
        bases, fields = self.models[name]; res = {}
        for b in bases:
            if b: res.update(self.model_fields(b, seen + (name,)) or {})
        for f, ann, required, dv in fields:
            if f.startswith("_"): continue
            if required: res[f] = sample(ann, f)
            elif isinstance(dv, (int, float, str, bool)): res[f] = dv
        return res

    def is_model(self, name):
        bases = self.models.get(name, ([], []))[0]
        return name == "BaseModel" or any(b == "BaseModel" or (b and b != name and self.is_model(b)) for b in bases) if name in self.models else False

    # ------------------------------------------------------------------ apps, routers, routes
    def collect(self):
        apps, routers, routes, edges, funcdefs = {}, {}, [], [], {}
        imports = {}
        for rel, tree in self.trees.items():
            imp = imports[rel] = {}
            for n in ast.walk(tree):
                if isinstance(n, ast.ImportFrom):
                    mod = "." * n.level + (n.module or "")
                    for a in n.names: imp[a.asname or a.name] = (mod, a.name)
                elif isinstance(n, ast.Import):
                    for a in n.names: imp[(a.asname or a.name).split(".")[0]] = (a.name, None)
            for n in ast.walk(tree):
                if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                    f = _name(n.value.func)
                    for t in n.targets:
                        if not isinstance(t, ast.Name): continue
                        if f == "FastAPI": apps[(rel, t.id)] = {}
                        elif f == "APIRouter":
                            pre = next((_s(k.value) for k in n.value.keywords if k.arg == "prefix"), None) or ""
                            routers[(rel, t.id)] = {"prefix": pre}
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and _name(n.func) == "include_router" and isinstance(n.func, ast.Attribute) and n.args:
                    pre = next((_s(k.value) for k in n.keywords if k.arg == "prefix"), "") or ""
                    edges.append((rel, _name(n.func.value), n.args[0], pre))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for d in n.decorator_list:
                        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in METHODS and isinstance(d.func.value, ast.Name):
                            p = _s(d.args[0]) if d.args else next((_s(k.value) for k in d.keywords if k.arg == "path"), None)
                            if p is not None: routes.append((rel, d.func.value.id, d.func.attr.upper(), p, n))
        return apps, routers, routes, edges, imports

    def ref(self, rel, node, imports):
        """(file, variable) a router expression refers to: a local name, `from x import router as r`, or `module.router`"""
        if isinstance(node, ast.Name):
            name = node.id; mod, orig = imports[rel].get(name, (None, None))
            if mod is None: return (rel, name)
            f = self.resolve(mod, rel); return (f, orig or name) if f else None
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            mod, orig = imports[rel].get(node.value.id, (None, None))
            if mod is None: return None
            f = self.resolve(mod + ("." + orig if orig else ""), rel) if not mod.startswith(".") else self.resolve(mod + ("." + orig if orig and not mod.endswith(".") else orig or ""), rel)
            if f is None and orig: f = self.resolve(mod, rel)
            return (f, node.attr) if f else None
        return None

    def scan(self):
        apps, routers, routes, edges, imports = self.collect()
        parents = {}    # child node -> [(parent node, include prefix)]
        for rel, pvar, rnode, pre in edges:
            child = self.ref(rel, rnode, imports); parent = (rel, pvar)
            if child and (parent in apps or parent in routers) and child in routers: parents.setdefault(child, []).append((parent, pre))
        def prefixes(node, depth=0):
            """every full prefix at which `node` is mounted, with the app it belongs to: [(app or None, prefix)]"""
            if node in apps: return [(node, "")]
            own = routers.get(node, {}).get("prefix", "")
            ups = parents.get(node, [])
            if not ups or depth > 6: return [(None, own)]
            return [(a, _join(p, inc, own) if (p or inc or own) else "") for par, inc in ups for a, p in prefixes(par, depth + 1)]
        idx = appscan._index(self.root); out = []
        for rel, var, method, path, fn in routes:
            node = (rel, var)
            if node in apps: mounts = [(node, "")]
            elif node in routers: mounts = prefixes(node)
            else: continue
            text = "\n".join(self.text[rel].splitlines()[min([d.lineno for d in fn.decorator_list] + [fn.lineno]) - 1:fn.end_lineno])
            rel_code = appscan.related_code(self.root, text, fn.name, index=idx)
            verdict, reasons = self.verdict(method, text + "\n" + rel_code)
            body, query, phs = self.params(fn, path)
            for app, pre in mounts:
                full = _join(pre, path) if (pre or path != "/") else "/"
                out.append({"method": method, "path": full, "function": fn.name, "file": rel, "lineno": min([d.lineno for d in fn.decorator_list] + [fn.lineno]),
                            "is_async": isinstance(fn, ast.AsyncFunctionDef), "app": self.spec(app) if app else None, "verdict": verdict, "reasons": reasons
                            + ([] if app else ["its router is not included in any app that was found"]),
                            "path_params": sorted(set(re.findall(r"{(\w+)(?::[^}]*)?}", full))), "body": body, "query": query,
                            "sample": {**{k: 1 for k in re.findall(r"{(\w+)(?::[^}]*)?}", full)}, **query, **(body or {})}})
        rank = {"suspect": 0, "writes": 1, "guarded": 2, "read-only": 3}
        out.sort(key=lambda r: (rank[r["verdict"]], r["path"], r["method"]))
        return {"apps": [{"spec": self.spec(k), "file": k[0], "routes": sum(1 for r in out if r["app"] == self.spec(k))} for k in apps], "routes": out}

    def spec(self, node):
        rel, var = node; tree = self.trees[rel]
        return f"{self.module_of(rel)}:{var}"

    def params(self, fn, path):
        """(body field samples or None, query value samples, path names) from the handler's signature"""
        holes = set(re.findall(r"{(\w+)(?::[^}]*)?}", path)); args = fn.args.args + fn.args.kwonlyargs
        defaults = [None] * (len(fn.args.args) - len(fn.args.defaults)) + list(fn.args.defaults) + list(fn.args.kw_defaults)
        body, query = None, {}
        for a, d in zip(args, defaults):
            if a.arg in ("self", "request", "response", "background_tasks") or a.arg in holes: continue
            dn = _name(d.func) if isinstance(d, ast.Call) else None
            if dn in ("Depends", "Security", "Header", "Cookie", "File", "Form", "UploadFile"): continue
            ann = _name(ann_base(a.annotation)) if a.annotation is not None else None
            if ann and self.is_model(ann) and dn != "Query": body = {**(body or {}), **(self.model_fields(ann) or {})}
            elif dn == "Body": body = {**(body or {}), a.arg: sample(a.annotation, a.arg)}
            else:
                required, dv = _dflt(d)
                if required: query[a.arg] = sample(a.annotation, a.arg)
                elif isinstance(dv, (int, float, str, bool)): query[a.arg] = dv
        return body, query, holes

    def verdict(self, method, text):
        low = text.lower()
        writes = bool(re.search(r"\.commit\(|\.add\(|\.add_all\(|\.merge\(|\.delete\(|\.flush\(|\bupdate\(|\binsert\(|insert\s+into|update\s+\w+\s+set|delete\s+from|\bsetattr\(|\s[-+]=\s", low))
        reads = bool(re.search(r"\.query\(|\bselect\b|\.first\(|\.one\(|\.one_or_none\(|\.scalars?\(|\.all\(|\.filter|\.get\(|\.execute\(|fetch", low))
        guards = [n for n, rx in GUARDS if re.search(rx, low, re.S)]
        if not writes and not reads: return "read-only", ["no database access seen in this function or the helpers it calls"]
        if not writes: return "read-only", ["only reads from the database"]
        if guards: return "guarded", ["uses " + ", ".join(guards) + ", which usually prevents this race"]
        if reads: return "suspect", ["reads data, then writes it back, with no lock or atomic UPDATE seen: two requests can both pass the check"]
        return "writes", ["writes to the database without reading first; duplicates are possible only if a unique constraint is missing"]

def ann_base(a):
    """`Optional[Model]` / `Model | None` -> Model"""
    if isinstance(a, ast.Subscript) and _name(a.value) in ("Optional", "Annotated"): s = a.slice; return s.elts[0] if isinstance(s, ast.Tuple) else s
    return a

# ---------------------------------------------------------------------- environment, schema and seed guesses
def db_env_guess(proj, alltext):
    names = re.findall(r"""(?:environ(?:\.get)?\s*[\[(]|getenv\s*\()\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""", alltext)
    for t in proj.trees.values():   # pydantic settings fields like `database_url: str` read DATABASE_URL
        for n in ast.walk(t):
            if isinstance(n, ast.ClassDef) and any(_name(b) in ("BaseSettings",) for b in n.bases):
                names += [s.target.id.upper() for s in n.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)]
    found = [n for n in dict.fromkeys(names) if re.search(r"DATABASE|_DB|DB_|POSTGRES|PG|DSN", n, re.I)]
    url = next((n for n in found if re.search(r"URL|URI|DSN", n, re.I)), None)
    pieces = {}
    for n in found:
        for tok, pg in (("HOST", "PGHOST"), ("PORT", "PGPORT"), ("USER", "PGUSER"), ("PASS", "PGPASSWORD"), ("NAME", "PGDATABASE"), ("DATABASE", "PGDATABASE")):
            if re.search(tok, n, re.I) and not re.search("URL|URI|DSN", n, re.I): pieces[n] = "${" + pg + "}"; break
    return {"guess": url or "DATABASE_URL", "found": found, "env": pieces if not url else {}}

def _stmts(sql):
    return [s.strip() for s in re.split(r";\s*(?:\n|$)", sql) if s.strip()]

def sql_guess(proj, root):
    """(schema_sql, seed_sql, source): from .sql files, else CREATE TABLE text in code, else SQLAlchemy models"""
    schema, seed = [], []
    for p in sorted(pathlib.Path(root).rglob("*.sql")):
        if set(p.relative_to(root).parts[:-1]) & appscan.SKIP_DIRS - {"migrations", "alembic"}: continue
        try: t = p.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError): continue
        for s in _stmts(re.sub(r"--[^\n]*", "", t)):
            low = s.lower().lstrip()
            if re.match(r"create\s+(unique\s+)?(table|index|type|sequence|view)|alter\s+table", low): schema.append(s + ";")
            elif low.startswith("insert"): seed.append(s + ";")
    if schema: return "\n".join(schema), "\n".join(seed), "your .sql files"
    found = []
    for t in proj.text.values():
        for m in re.finditer(r"create\s+table\s+(?:if\s+not\s+exists\s+)?[\w.\"]+\s*\(", t, re.I):
            depth, i = 1, m.end()
            while i < len(t) and depth: depth += (t[i] == "(") - (t[i] == ")"); i += 1
            found.append(re.sub(r"\s+", " ", t[m.start():i]).strip() + ";")
    if found: return "\n".join(dict.fromkeys(found)), "", "CREATE TABLE statements found in your code"
    sch, sd = models_sql(proj)
    if sch: return sch, sd, "your SQLAlchemy models (a best guess: check the column types)"
    return "", "", None

def models_sql(proj):
    tables = []
    for tree in proj.trees.values():
        for c in ast.walk(tree):
            if not isinstance(c, ast.ClassDef): continue
            tn = next((_s(s.value) for s in c.body if isinstance(s, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in s.targets)), None)
            if not tn: continue
            cols = []
            for s in c.body:
                name = ann = call = None
                if isinstance(s, ast.Assign) and isinstance(s.value, ast.Call) and _name(s.value.func) == "Column" and isinstance(s.targets[0], ast.Name): name, call = s.targets[0].id, s.value
                elif isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name) and isinstance(s.value, ast.Call) and _name(s.value.func) in ("mapped_column", "Column"): name, call, ann = s.target.id, s.value, s.annotation
                if not name: continue
                typ = next((SQL_TYPES.get(_name(a.func) if isinstance(a, ast.Call) else _name(a)) for a in call.args if SQL_TYPES.get(_name(a.func) if isinstance(a, ast.Call) else _name(a))), None)
                if typ is None and ann is not None: typ = PY_TYPES.get(ast.unparse(ann_base(ann.slice if isinstance(ann, ast.Subscript) and _name(ann.value) == "Mapped" else ann)).replace("Optional[", "").rstrip("]"), "text")
                typ = typ or "text"; kw = {k.arg: k.value for k in call.keywords}; pk = isinstance(kw.get("primary_key"), ast.Constant) and kw["primary_key"].value
                fk = next((_s(a.args[0]) for a in call.args if isinstance(a, ast.Call) and _name(a.func) == "ForeignKey" and a.args), None)
                d = ["serial primary key" if pk and typ in ("integer", "bigint") else typ + (" primary key" if pk else "")]
                if isinstance(kw.get("nullable"), ast.Constant) and kw["nullable"].value is False and not pk: d.append("not null")
                if isinstance(kw.get("unique"), ast.Constant) and kw["unique"].value: d.append("unique")
                if isinstance(kw.get("default"), ast.Constant) and kw["default"].value is not None and not pk:
                    v = kw["default"].value; d.append("default " + (f"'{v}'" if isinstance(v, str) else str(v).lower() if isinstance(v, bool) else str(v)))
                if fk and "." in fk: d.append(f"references {fk.split('.')[0]}({fk.split('.')[1]})")
                cols.append((name, typ, pk, " ".join(d)))
            if cols: tables.append((tn, cols))
    schema = "\n".join(f"CREATE TABLE {t} (\n  " + ",\n  ".join(f"{n} {d}" for n, _, _, d in cols) + "\n);" for t, cols in tables)
    seed = []
    for t, cols in tables:
        use = [(n, ty) for n, ty, pk, _ in cols if not (pk and ty in ("integer", "bigint"))]
        vals = [("1" if any(k in n.lower() for k in STOCKY) else "100" if "balance" in n.lower() else "1") if ty in ("integer", "bigint", "smallint", "numeric", "double precision")
                else "true" if ty == "boolean" else "now()" if ty.startswith("timestamp") else "CURRENT_DATE" if ty == "date" else "'test'" for n, ty in use]
        if use: seed.append(f"INSERT INTO {t} ({', '.join(n for n, _ in use)}) VALUES ({', '.join(vals)});")
    return schema, "\n".join(seed)

def scan(root):
    """the whole static report for the project folder `root`"""
    proj = Project(root); res = proj.scan(); alltext = "\n".join(proj.text.values())
    schema_sql, seed_sql, source = sql_guess(proj, root); env = db_env_guess(proj, alltext); warnings = []
    if not res["apps"]: warnings.append("No FastAPI app was found (looked for `x = FastAPI(...)`). If your app is built inside a function, type the name of a variable that holds it in the setup form.")
    if getattr(proj, "broken", []): warnings.append("These files could not be parsed and were left out of the scan: " + ", ".join(proj.broken[:5]))
    if re.search(r"create_async_engine|asyncpg|AsyncSession|aiopg|psycopg_pool|import psycopg\b|from psycopg import", alltext) and "psycopg2" not in alltext:
        warnings.append("Your app seems to use an async or psycopg3 driver. GlitchHunter cannot slow down its database reads to make a race visible, so a race may be rare.")
    if re.search(r"""["']postgres(ql)?(\+\w+)?://""", alltext): warnings.append("A literal postgresql:// address appears in your code. If the app uses it instead of an environment variable, it will not reach the private database.")
    if re.search(r"create\s+extension", schema_sql, re.I): warnings.append("The schema contains CREATE EXTENSION, which the private role may not run: remove it.")
    return {**res, "db_env": env, "schema_sql": schema_sql, "seed_sql": seed_sql, "schema_source": source, "warnings": warnings,
            "py_files": len(proj.trees), "risky": sum(1 for r in res["routes"] if r["verdict"] == "suspect")}

def suggested_config(rep):
    """the pre-filled setup for the most suspicious supported route"""
    r = next((x for x in rep["routes"] if x["app"] and x["method"] != "GET"), None) or next((x for x in rep["routes"] if x["app"]), None)
    if not r: return None
    item = dict(r["sample"]); burst = [dict(item) for _ in range(4)]
    return {"app": r["app"], "file": r["file"], "func": r["function"], "method": r["method"], "path": r["path"], "body": "json" if r["body"] else "query", "burst": burst,
            "schema_sql": rep["schema_sql"], "seed_sql": rep["seed_sql"], "db_env": rep["db_env"]["guess"], "env": rep["db_env"]["env"]}
