# Try your own app (upload a third-party app)

Upload a FastAPI + PostgreSQL app and GlitchHunter starts it, finds its endpoints, attacks one with simultaneous requests, shows what goes wrong, and tests an AI-proposed fix. Dashboard: `/try`. CLI: `.\glitchhunter upload ...` (see `docs/cli.md`). Needs live mode (`NEXT_PUBLIC_USE_MOCK=false`).

## Preparing a real app: checklist
1. **Pick the endpoint**: one that reads a value and then writes it (stock, balance, quota, counter, "claim a coupon"). The scan ranks "reads, then writes" endpoints first.
2. **Install its Python packages here**: `pip install -r requirements.txt` in the environment that runs GlitchHunter. There is no isolation: the app runs with whatever is installed. If a package is missing the upload says which one.
3. **Zip the app folder** (without `venv`, `.git`, `node_modules`; limit 2 MB / 300 files), or upload a single `.py` if it is self-contained. Package layouts (`app/main.py` with relative imports, routers, services) work as a zip.
4. **Setup SQL**: statements that reset the tables the endpoint touches and insert a few starting rows. Easiest: run the app's migrations on a scratch database, `pg_dump --schema-only`, then add `INSERT` rows. If your app creates its own tables on start-up, use `TRUNCATE ... RESTART IDENTITY; INSERT ...` instead: the app is started once before the SQL runs. Keep it to the tables that matter (limit 30).
5. **Database address**: the app must read it from an environment variable (default `DATABASE_URL`). SQLAlchemy apps often need the URL style `postgresql+psycopg2://` (SQLAlchemy 2.1 picks the psycopg3 driver for a plain `postgresql://`).
6. **Extra environment variables** the app needs (`API_TOKEN`, `SECRET_KEY`, ...): `NAME=value`, one per line. Stored on this computer in `runs/projects/` (git-ignored). Use test values.
7. **Login**: if the endpoint needs a token or API key, enter a test value that the app accepts as the header value (for example `Bearer test-token`). One static header is supported.

## What it understands (and how)
GlitchHunter **imports your app in a subprocess and asks FastAPI what it serves** (`controller/inject/inspect_app.py`), so it does not guess from source files:
- **Routers and prefixes**: full paths such as `/api/v1/orders` are exact, including nested `include_router(..., prefix=...)`.
- **JSON bodies**: a sample body is built from the OpenAPI schema (required fields, enums, formats, min/max); you can edit it. Path values and query values likewise.
- **Auth**: security schemes and required `Authorization` / API-key headers are detected and asked for.
- **Source location**: each route's handler file and line come from the running app, so the AI reads the right function and a fix replaces exactly that function (decorators must stay the same).
- **Related code**: the helper functions the handler calls (up to two levels) and the model classes it uses are shown to the AI, because the real logic often lives in a service module.
- **Number to watch**: the numeric column the code assigns or decrements (for example `products.stock`) is suggested from the real schema; you can change it. The "quantity" field is guessed from the request values.
- **Unsupported flags**: endpoints that need a form or file upload, a cookie login, or whose code lives in an installed library are listed with the reason and cannot be selected.

## How the attack and the checks work
- **Isolation**: each project gets its own PostgreSQL schema `p_<id>`; the app, the setup SQL, the attacker and the checks all use it as `search_path`. Deleting the project drops it.
- **Snapshots**: before each try every table `T` is copied to `snap_T`; checks relate `snap_T`, the request log `ops_log` (all request values in `params` jsonb, and the HTTP `status`; any 2xx counts as success) and the final tables.
- **Checks**: the AI proposes them from the endpoint, its helpers and the live schema. There is **no built-in check** for uploaded apps, so a person approves at least one. The filter drops checks that fire on one-at-a-time runs and marks checks that never fire under concurrency as uninformative. Recall is not measured.
- **Making the race visible**: the test copy starts with `controller/inject/sitecustomize.py` on `PYTHONPATH` and `GH_RACE_PAUSE_MS` (default 25): every `SELECT` sleeps afterwards, through **psycopg2** and through **synchronous SQLAlchemy** engines (an `after_cursor_execute` listener). This widens the read-check-write gap in the test copy only. Without it a race was rare (1 of 50 tries); with it 48 to 50 of 50.
- **Repair**: the prompt shows the handler, the whole file (so it knows which names exist), and the related code. The fix may add imports **inside the function** from fastapi, sqlalchemy, pydantic, typing, datetime, decimal, uuid, math or the project's own modules (never os, sys, subprocess). It runs on a **copy of the whole project folder** and is accepted only if (a) one-request-at-a-time behaviour matches the **original app** (statuses and final value), (b) the failing schedule replays clean, (c) two batches of fresh simultaneous tries show no violation. The original code goes through the same validation as a negative control. If a fix fails, the app's own error output is sent back to the AI. Uploaded files are never edited; the fix is shown as code to copy.

## What was tested
1. A small psycopg2 app (ticket shop): upload, checks, attack (50 of 50), repair accepted, control rejected the original.
2. A stand-in "third-party style" app **written by us**: package layout, SQLAlchemy ORM, a helper in a services module, routers with a nested prefix (`/api/v1/orders`), a Pydantic JSON body, a required `Authorization` header, settings that need an extra environment variable, `201` responses. Through the dashboard: scan found the nested path, the body sample, the auth header and the classic pattern; the AI proposed checks (the filter dropped one wrong check); the attack failed 50 of 50 (stock 3, six orders approved); repair was accepted with a different approach than the demo apps (a raw `SELECT ... FOR UPDATE` before the helper, with an import inside the function) and the control rejected the original. Its first repair attempt failed because the AI used a name the file did not import: the validator rejected it, which led to the import rule and the better error feedback above.
**No real third-party app from the internet has been tried.** Two stand-ins are not evidence of generality.

## Limits
- FastAPI + PostgreSQL. psycopg2 or **synchronous** SQLAlchemy. **Async drivers** (asyncpg, SQLAlchemy async, psycopg3 async) are not covered by the pause: a race may be rare (the upload warns when it sees them).
- No form or file bodies, no cookie logins, no token refresh or login flows (one static header only), no WebSockets.
- One endpoint per scenario; the "number to watch" is one column (summed over the table).
- A fix replaces one function. A bug whose proper fix is in another file (a service, a model constraint, a migration) can only be fixed if the AI can do it inside the handler (for example by locking the row first). Constraint-based fixes (unique indexes) are not applied.
- Dependencies are not isolated and Python-version conflicts are not handled.
- **The uploaded code is run on this machine** (to inspect it, to attack it, and the AI-written patch runs on a copy). API keys are removed from its environment, but there is no sandbox. Only upload code you trust and never expose the API publicly with this feature on.
- A fix is only as good as the approved checks. "Passed" is evidence, not proof.

## API
- `POST /projects` `{name, filename, content_b64, setup_sql, db_env, db_scheme, env}` returns the project (`id`, `tables`, `columns`, `entry`, `endpoints[...]`, `suggested_state`, `warnings`, `env_names`). Environment values are never returned. Errors: 422 with a plain message.
- `POST /projects/{id}/scenario` `{method, path, params, path_params, json, headers, race_n, state, qty_key, pause_ms}` creates scenario `custom_<id>`; it then appears in `GET /scenarios` (header **values** are never returned, only `header_names`).
- `GET /projects`, `DELETE /projects/{id}` (stops the app, drops the schema, removes the files).
- Files live under `runs/projects/<id>/` (git-ignored). `GH_CORS_ORIGINS` (comma list) allows more dashboard origins.
