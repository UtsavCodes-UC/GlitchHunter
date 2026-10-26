"""Load gh.yml (or gh.example.yml) and resolve scenarios. No secrets here: the database URL comes from the environment.
Scenarios uploaded through "Try your own app" live in runs/projects/<id>/scenario.json and are merged in automatically."""
import os, json, pathlib, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "runs" / "projects"

def custom_scenarios():
    out = {}
    for f in sorted(PROJECTS.glob("*/scenario.json")) if PROJECTS.exists() else []:
        try: sc = json.loads(f.read_text(encoding="utf-8")); out[sc["id"]] = sc
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

def with_schema(url, schema):
    """the same database URL, but every connection starts in `schema` (how an uploaded project is kept apart from the demo tables)"""
    return f"{url}{'&' if '?' in url else '?'}options=-c%20search_path%3D{schema}"

INJECT_DIR = ROOT / "controller" / "inject"

def test_env(base_env, sc, cfg=None):
    """environment for a test copy of an uploaded app: no API keys, the project's schema as search_path, and the SELECT pause"""
    env = {k: v for k, v in base_env.items() if "API_KEY" not in k.upper()}
    if sc.get("custom"):
        env.update(sc.get("env") or {})                       # the project's extra environment variables (settings, tokens)
        url = with_schema(database_url(cfg), sc["schema"]); scheme = sc.get("db_scheme") or "postgresql"
        if scheme != "postgresql" and url.startswith("postgresql"): url = scheme + url[len("postgresql"):]   # e.g. postgresql+psycopg2://
        env[sc["db_env"]] = url
        env["PYTHONPATH"] = str(INJECT_DIR) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["GH_RACE_PAUSE_MS"] = str(sc.get("pause_ms", 25))
    return env

def scenario(cfg, name):
    if name not in cfg["scenarios"]: raise KeyError(f"unknown scenario {name!r}; known: {list(cfg['scenarios'])}")
    return {**cfg["scenarios"][name], "name": name}

def app_path(sc):
    return pathlib.Path(sc["app_file"]) if pathlib.Path(sc["app_file"]).is_absolute() else ROOT / sc["app_file"]
