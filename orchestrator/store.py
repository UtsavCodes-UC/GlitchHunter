"""Tiny JSON persistence under runs/state/ (git-ignored): invariants per scenario."""
import json
from controller import config

def _path(sc_name):
    d = config.ROOT / "runs" / "state"; d.mkdir(parents=True, exist_ok=True)
    return d / f"{sc_name}_invariants.json"

def load_invariants(sc_name):
    p = _path(sc_name)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []

def save_invariants(sc_name, invs):
    _path(sc_name).write_text(json.dumps(invs, indent=2, default=str), encoding="utf-8")
    return invs

def set_status(sc_name, inv_id, status):
    invs = load_invariants(sc_name)
    for i in invs:
        if i["id"] == inv_id: i["status"] = status; save_invariants(sc_name, invs); return i
    raise KeyError(inv_id)

def approved(sc_name):
    """{id: sql} of invariants a human approved"""
    return {i["id"]: i["sql"] for i in load_invariants(sc_name) if i["status"] == "approved"}
