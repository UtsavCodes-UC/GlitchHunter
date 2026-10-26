# Contracts (DRAFT v0 — agreed names and shapes; change only by pull request + message to the team)

Owners: apps = Person 2, dashboard = Person 3, orchestrator + controller = Utsav. All JSON field names are lower_snake_case.

## Data the rules query (exactly as stored)
- `ops_log(op_id serial, endpoint text, amount int, qty int, user_id int, code text, status int)` — one row per request. `endpoint` is stored WITH a leading slash, e.g. `/withdraw`. `status` is the HTTP status (200 ok, 409 rejected).
- `initial_state(balance int, stock int)` — exactly one row, the state BEFORE the run.
- The app's own tables hold the FINAL state. Wallet: `wallet(id int, balance int)`. Inventory: `inventory(sku int, stock int)`.
- The attacker (controller) writes `ops_log` and `initial_state` itself. Apps must NOT log requests.
- An invariant is ONE PostgreSQL SELECT that returns zero rows when it holds and at least one row when violated.

## Target app requirements (apps/)
- `POST /reset?balance=<int>&stock=<int>` recreates tables and sets the starting state.
- Wallet: `POST /withdraw?amount=<int>` → 200 `{"ok": true}` or 409 when insufficient.
- Inventory: `POST /checkout?qty=<int>` → 200 or 409 when out of stock.
- `GET /state` returns the app's current state as JSON.
- Optional test-only header `X-Race-Delay: <ms>` pauses between the check and the write (buggy mode only).
- One file per scenario; mode flag `MODE=vuln|fixed` read from the environment; port from the command line.

## Config (`gh.yml`, see `gh.example.yml`)
`base_url`, `database_url_env` (name of an environment variable), `start_command`, `reset`, `endpoints[{method, path, params}]`, optional `auth_headers`.

## Invariant
```json
{"id": "wallet.conservation", "name": "balance_conservation", "english": "money out + money left = money in",
 "sql": "SELECT 1 FROM initial_state i, wallet w WHERE ...", "source": "llm",
 "status": "proposed", "stats": {"sequential_fires": 0, "concurrent_fires": 48, "recall_on_race": 1.0}}
```
`source`: llm | mined | manual. `status`: proposed | approved | dropped | uninformative.

## Trial result
```json
{"run_id": "r_001", "scenario": "wallet", "n": 2, "delay_ms": 0, "trial": 0,
 "initial_state": {"balance": 100},
 "requests": [{"req": 0, "method": "POST", "path": "/withdraw", "params": {"amount": 80}, "status": 200, "start_ms": 1.2, "end_ms": 36.0}],
 "final_state": {"balance": 20},
 "violations": {"wallet.conservation": [[100, 20, 160]]}}
```
A failing schedule is a trial result that has at least one violation plus enough inputs (`n`, `delay_ms`, `params`, `initial_state`) to replay it.

## Repair attempt
```json
{"attempt": 1, "strategy": "select_for_update", "explanation": "...",
 "patch": {"file": "apps/wallet_app.py", "function": "withdraw", "code": "..."},
 "validation": {"regression_failures": [], "replay": {"trials": 1, "violations": 0},
                "fresh_trials": [{"delay_ms": 0, "trials": 50, "violations": 0}, {"delay_ms": 30, "trials": 50, "violations": 0}],
                "throughput_rps": 0.0},
 "accepted": true, "reason": ""}
```

## Orchestrator API (FastAPI)
- `POST /scenarios/{id}/propose` → `{"invariants": [Invariant]}`
- `POST /scenarios/{id}/filter` → `{"invariants": [Invariant]}` (with `stats` and `status`)
- `POST /scenarios/{id}/attack` body `{"n": 2, "trials": 50, "delay_ms": 0}` → `{"run_id": "...", "summary": {...}}`
- `POST /scenarios/{id}/repair` → `{"attempts": [RepairAttempt], "accepted": bool}`
- `GET /runs/{run_id}` → trial results
- Until each endpoint is live, the dashboard uses the mock files in `docs/examples/`.
