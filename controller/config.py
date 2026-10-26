"""Load gh.yml (or gh.example.yml) and resolve scenarios. No secrets here: the database URL comes from the environment.
Scenarios uploaded through "Try your own app" live in runs/projects/<id>/scenario.json and are merged in automatically."""
import os, json, pathlib, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "runs" / "projects"

def custom_scenarios():
    out = {}
    for f in sorted(PROJECTS.glob("*/scenario.json")) if PROJECTS.exists() else []:
        try:
            sc = json.loads(f.read_text(encoding="utf-8"))
            if "role" in sc: out[sc["id"]] = sc          # scenario files of the older upload format have no role: ignored
        except (ValueError, KeyError): continue
    return out

def load(path=None):
    p = path or os.environ.get("GH_CONFIG")
    p = pathlib.Path(p) if p else (ROOT / "gh.yml" if (ROOT / "gh.yml").exists() else ROOT / "gh.example.yml")
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")); cfg.setdefault("scenarios", {})
    cfg["scenarios"].update(custom_scenarios())
    return cfg

def database_url(cfg):
    name = cfg.get("database_url_env", "GH_DATABASE_URL")
    url = os.environ.get(name)
    if not url: raise RuntimeError(f"{name} is not set in this environment")
    return url

def admin_url(cfg):
    """the server user that may create/drop the per-project roles (default: the main database URL)"""
    return os.environ.get("GH_ADMIN_DATABASE_URL") or database_url(cfg)

def project_parts(cfg, sc):
    """host, port, database and the PROJECT's own role/password (never the main user's)"""
    from urllib.parse import urlparse
    u = urlparse(database_url(cfg))
    return {"host": u.hostname or "localhost", "port": str(u.port or 5432), "dbname": (u.path or "/").lstrip("/"), "user": sc["role"], "password": sc["role_password"]}

def project_url(cfg, sc, scheme=None):
    """connection URL of an uploaded project's isolated role; its search_path (the project's schema) is a role setting"""
    from urllib.parse import quote
    p = project_parts(cfg, sc)
    url = f"postgresql://{quote(p['user'], safe='')}:{quote(p['password'], safe='')}@{p['host']}:{p['port']}/{p['dbname']}"
    if scheme and scheme != "postgresql": url = scheme + url[len("postgresql"):]   # e.g. postgresql+psycopg2://
    return url

INJECT_DIR = ROOT / "controller" / "inject"
SAFE_ENV = ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP", "TMPDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL")

def test_env(base_env, sc, cfg=None, home=None):
    """environment for a test copy of an uploaded app. Uploaded projects get a MINIMAL environment (a short allow-list, the project's
    own database role, its extra variables and the SELECT pause): none of our API keys, passwords or other settings."""
    if not sc.get("custom"):
        return {k: v for k, v in base_env.items() if "API_KEY" not in k.upper()}
    env = {k: base_env[k] for k in SAFE_ENV if k in base_env}
    env.update(PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
    if home: env.update(HOME=str(home), TEMP=str(home), TMP=str(home), TMPDIR=str(home))
    p = project_parts(cfg, sc)
    pg = {"PGHOST": p["host"], "PGPORT": p["port"], "PGUSER": p["user"], "PGPASSWORD": p["password"], "PGDATABASE": p["dbname"]}
    url = project_url(cfg, sc, sc.get("db_scheme"))
    import re
    for k, v in (sc.get("env") or {}).items():                 # extra variables; ${PGHOST}-style placeholders mean "the project's database" (no passwords typed)
        env[k] = re.sub(r"\$\{(\w+)\}", lambda m: pg.get(m.group(1), url if m.group(1) == "DB_URL" else m.group(0)), str(v))
    env.update(pg); env[sc["db_env"]] = url
    env["PYTHONPATH"] = str(INJECT_DIR)
    env["GH_RACE_PAUSE_MS"] = str(sc.get("pause_ms", 25))
    return env

def scenario(cfg, name):
    if name not in cfg["scenarios"]: raise KeyError(f"unknown scenario {name!r}; known: {list(cfg['scenarios'])}")
    return {**cfg["scenarios"][name], "name": name}

def app_path(sc):
    return pathlib.Path(sc["app_file"]) if pathlib.Path(sc["app_file"]).is_absolute() else ROOT / sc["app_file"]
