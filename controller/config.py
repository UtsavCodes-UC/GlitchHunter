"""Load gh.yml (or gh.example.yml) and resolve scenarios. No secrets here: the database URL comes from the environment."""
import os, pathlib, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent

def load(path=None):
    p = path or os.environ.get("GH_CONFIG")
    p = pathlib.Path(p) if p else (ROOT / "gh.yml" if (ROOT / "gh.yml").exists() else ROOT / "gh.example.yml")
    return yaml.safe_load(p.read_text(encoding="utf-8"))

def database_url(cfg):
    name = cfg.get("database_url_env", "GH_DATABASE_URL")
    url = os.environ.get(name)
    if not url: raise RuntimeError(f"{name} is not set in this environment")
    return url

def scenario(cfg, name):
    if name not in cfg["scenarios"]: raise KeyError(f"unknown scenario {name!r}; known: {list(cfg['scenarios'])}")
    return {**cfg["scenarios"][name], "name": name}

def app_path(sc):
    return pathlib.Path(sc["app_file"]) if pathlib.Path(sc["app_file"]).is_absolute() else ROOT / sc["app_file"]
