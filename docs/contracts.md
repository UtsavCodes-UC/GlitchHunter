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

## Config (`gh.yml`, falls back to `gh.example.yml`; see that file for every field)
Top level: `database_url_env` (NAME of the environment variable holding the Postgres URL, e.g. `GH_DATABASE_URL`) and `scenarios:` (wallet, inventory). Each scenario has `base_url`, `candidate_port`, `app_file`, `endpoint{method,path,params}`, `reset{path,params}`, `state_path`, `tables`, `initial_columns`, `race_n`, `conservation`, `oracle`, `regression`, `throughput`.

## App file convention (needed by the repair tool)
Each endpoint function starts at its `@app.post("/path")` decorator and ends at a line `# END-ENDPOINT` directly after it. Both `MODE == "vuln"` and `MODE == "fixed"` branches live inside that one function (the repair tool shows the LLM only the vulnerable branch). Module-level names that patches rely on: `app`, `Conn`, `hook`, `Header`, `HTTPException`.

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
- `GET /runs/{run_id}` → `{"summary": {...}, "failing_trials": [Trial result]}`
- `GET /scenarios` → `[{"id", "endpoint", "invariants": <count>}]`; `GET /scenarios/{id}/invariants` → `{"invariants": [Invariant]}`
- `PATCH /scenarios/{id}/invariants/{invariant_id}` body `{"status": "approved"|"rejected"|"proposed"}` → the updated Invariant (a human decision is never overwritten by a later propose)
- `POST .../attack` returns `{"run_id", "summary": {trials, trials_with_violation, races_observed, per_invariant, invariants_used, human_approved}, "first_failing_trial": Trial result | null}`; `POST .../repair` returns `{"attempts": [RepairAttempt], "accepted": bool, "negative_control": {"buggy_code_accepted", "validator_working", "reason"}, "evidence": Trial result}`
- Invariants carry an optional `note` (why the filter dropped / kept it). Only one operation runs at a time: a second request gets HTTP 409.
- Run the API from the repo root: `python -m uvicorn orchestrator.api:app --port 9000` (CORS allows http://localhost:3000). Needs `GH_DATABASE_URL` and the target app running in `MODE=vuln`.
- Until each endpoint is live, the dashboard uses the mock files in `docs/examples/`.
