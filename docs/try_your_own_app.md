# Try your own app (upload feature)

Upload a small FastAPI + PostgreSQL app and GlitchHunter attacks one endpoint with simultaneous requests, shows what goes wrong, and tests an AI-proposed fix. Dashboard page: `/try`. Needs live mode (`NEXT_PUBLIC_USE_MOCK=false`).

## What the user provides
1. A name.
2. The app: one `.py` file or a `.zip` of the folder (max 2 MB; unzipped max 20 MB / 300 files).
3. A **setup SQL**: `DROP/CREATE TABLE ...` plus the starting rows. It is rerun before every try.
4. The name of the environment variable the app reads for its database URL (default `DATABASE_URL`).
Then they pick an endpoint (the scan ranks "reads, then writes" endpoints first), the request values (JSON), how many simultaneous requests (2 to 20, default 6), and which numeric column to watch (suggested automatically).

## How it works
- **Isolation:** each project gets its own PostgreSQL schema `p_<id>`. The app, the setup SQL, the attacker and the checks all run with that schema as `search_path`, so the demo tables are never touched. Deleting the project drops the schema.
- **Snapshots instead of `initial_state`:** before each try every app table `T` is copied to `snap_T` (the state before the run). Checks relate `snap_T`, the request log `ops_log` (with all request values in `params` jsonb, and `status`), and the final table.
- **Checks:** the AI proposes them from the endpoint code and live schema (`orchestrator/prompts/invariants_custom_template.txt`). There is **no built-in check** for uploaded apps, so a person must approve at least one. The filter works as for the demos (dropped if it fires on one-at-a-time runs; uninformative if it never fires under concurrency). **Recall is not measured** because uploaded apps have no race oracle.
- **Making the race visible:** the app is started for testing with `controller/inject/sitecustomize.py` on `PYTHONPATH` and `GH_RACE_PAUSE_MS=25`: every psycopg2 `SELECT` sleeps 25 ms afterwards. This widens the read-check-write gap in the test copy only; it is the same idea as the demo apps' `X-Race-Delay` hook but needs no code change. Without it the race was rare in our test (1 of 50 tries with 6 simultaneous requests); with it, 48 to 50 of 50.
- **Repair:** the prompt shows the whole endpoint file for context. The fix is run on a **copy of the whole project folder** and accepted only if (a) one-request-at-a-time behaviour matches the **original app** (statuses and final value, since there are no hand-written regression cases), (b) the failing schedule replays clean, (c) two batches of fresh simultaneous tries show no violation. The original code is run through the same validation as a negative control. Uploaded files are never edited; the fix is shown as code to copy.

## Limits (be honest about them)
- FastAPI + **psycopg2** + PostgreSQL only. The pause injection does not cover SQLAlchemy-async, psycopg3 or asyncpg.
- Endpoints must be declared on the app object (`@app.post("/x")`), use **query parameters**, and have no `{path}` parameters. No routers with prefixes, no JSON bodies, no login.
- The app must read its database URL from an environment variable. If it hard-codes the connection string it will use the wrong database (the scan warns when the variable name is not found in the code).
- **The uploaded code is run on this machine.** API keys are removed from its environment, but there is no sandbox. Only upload code you trust. Do not expose the API publicly with this feature on.
- A fix is only as good as the checks. A wrong or weak check can accept a bad fix. "Passed" is evidence, not proof.
- Tested on one sample app written in a different style from the demo apps (ticket shop): upload, scan, AI checks, attack (50 of 50), repair (accepted on attempt 1, negative control rejected the original). That is one app, not evidence of generality.

## API
- `POST /projects` `{name, filename, content_b64, setup_sql, db_env}` returns the project (`id`, `tables`, `entry`, `endpoints[{method,path,function,file,params,sample_params,supported,hint}]`, `suggested_state`, `warnings`). Errors: 422 with a plain message.
- `POST /projects/{id}/scenario` `{method, path, params, race_n, state?}` creates scenario `custom_<id>`; it then appears in `GET /scenarios` (with `custom: true`, `title`, `race_n`) and works with every `/scenarios/{id}/...` endpoint. The app is started on demand.
- `GET /projects`, `DELETE /projects/{id}` (stops the app, drops the schema, removes the files).
- Files live under `runs/projects/<id>/` (git-ignored). Set `GH_CORS_ORIGINS` (comma list) to allow more dashboard origins.
