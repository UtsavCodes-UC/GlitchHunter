# Your own code (upload a FastAPI + PostgreSQL project)

Drop a `.zip`, some files or a whole folder on the home page. GlitchHunter **reads** it (nothing is run), shows the endpoints with a hint per endpoint,
asks for a short setup, runs the app **once** in isolation to test that setup, and from then on the project goes through the same pages as the built-in examples
(checks, attack, repair). CLI: `.\glitchhunter upload PATH`, `setup ID`, `delete-project ID` (see `docs/cli.md`). Needs live mode (`NEXT_PUBLIC_USE_MOCK=false`).

## Needs (once): permission to create database roles
Each project gets its own PostgreSQL role and schema. The database user in `GH_DATABASE_URL` (or `GH_ADMIN_DATABASE_URL` if you set it) must be allowed to create roles. As a superuser (in psql as `postgres`):
```sql
ALTER ROLE rh CREATEROLE;
```
Without it the first "Save and test" fails with exactly this instruction. Nothing is created in the database before that point.

## The flow
1. **Upload.** Limits (change with environment variables): zip 3 MB (`GH_UPLOAD_ZIP_MAX`), one file 1 MB (`GH_UPLOAD_FILE_MAX`), 10 MB in total (`GH_UPLOAD_TOTAL_MAX`), 400 files (`GH_UPLOAD_MAX_FILES`), 25 projects (`GH_UPLOAD_MAX_PROJECTS`). Only text/source files are kept (`.py .txt .md .sql .json .yaml .yml .toml .cfg .ini .html .csv .rst`); `venv`, `.git`, `node_modules`, `__pycache__`, hidden folders and dotfiles are skipped. Refused: absolute paths, `..`, symlinks in a zip, files that are not UTF-8, uploads without a `.py` file. A single top folder is stripped. The project name defaults to the zip or folder name.
2. **Static scan** (`orchestrator/scan.py`; `ast` and regular expressions only, **never imports or runs your code**): FastAPI apps and routers with their `include_router` prefixes, every route with its path/query/body fields, a **hint** per route, a guess of the environment variable for the database address, and a guess of the schema SQL (from `.sql` files, `CREATE TABLE` text in code, or SQLAlchemy models) and of seed rows.
   - `looks risky`: reads data, then writes it back, with no lock or atomic UPDATE in sight. `guarded`: uses `SELECT ... FOR UPDATE`, an advisory lock, `ON CONFLICT`, an atomic conditional `UPDATE`, or a strict isolation level. `writes`: writes without reading first. `read-only`.
   - These are **hints from code patterns, not verdicts**. A guarded-looking route can still be wrong and a risky-looking one can be fine.
3. **Setup** (pre-filled): how to start the app (`pkg.module:attr`), the file and function of the endpoint, method, path with `{placeholders}`, whether other values go in a JSON body or the query string, the **burst** (2 to 50 JSON objects, one per request; they may differ), schema SQL, seed SQL, the environment variable for the database address, extra environment variables (`${PGHOST}`, `${PGPORT}`, `${PGUSER}`, `${PGPASSWORD}`, `${PGDATABASE}`, `${DB_URL}` expand to this project's private database, so no password is typed), an optional login header, the URL style (`postgresql+psycopg2` for SQLAlchemy 2.1) and the test pause.
4. **Save and test the setup**: creates the role and schema, runs the schema SQL, starts the app in isolation, loads the seed rows, sends the burst once and reports honestly: any 5xx is a **server error** (with the app's last output); no 2xx or any 422 is a **warning** (requests rejected); otherwise **ok**. A live log is shown. Only then does the project become a scenario (`set up`).
5. **Edit or delete.** Editing the setup removes the old test result until it is tested again. Delete stops the app, terminates the role's sessions, drops the schema and the role, and removes the files, checks and results.

## What runs when
- Upload, scan, saving a setup, showing source: your code is only read.
- Setup test, attack, repair validation: your code runs, on a **fresh temporary copy** of the files, as a separate process (own process group), with a **minimal environment** (a short allow-list such as `PATH`, `SYSTEMROOT`, `TEMP`, plus the project's own database variables and the extra variables you gave). None of our API keys, the main database URL or other settings are passed on. `requirements.txt` is never installed: the libraries available are the ones installed for GlitchHunter itself (fastapi, pydantic, psycopg2, psycopg 3, sqlalchemy, asyncpg, httpx).

## Isolation: what is and is not isolated
- **Database (isolated):** one role `gh_up_<id>` and one schema `up_<id>` per project (`NOSUPERUSER NOCREATEDB NOCREATEROLE`, 80 connections, statement and idle-in-transaction timeouts). The role owns only its schema. Verified with `python samples/isolation_probe.py`: it could not read another table of the main database or another project's schema, and could not create a schema, a role, or a table in `public`; `pg_read_file`, `pg_shadow`, `SET ROLE` and `COPY ... TO PROGRAM` were all denied, and it saw no API key or main database URL in its environment. (It can still see catalog names, such as table names, that PostgreSQL shows to every role.)
- **Process (partly isolated):** fresh temp copy, minimal environment, own process group. On Linux/macOS also resource limits (CPU, memory, file size, open files, core dumps) and, when GlitchHunter runs as root, a switch to an unprivileged user. **These POSIX parts were written but NOT run on this Windows machine** (no Docker/WSL here); on Windows only the copy, the minimal environment and the process group apply.
- **NOT isolated:** outbound network access (the uploaded app can reach any host the machine can), CPU/memory on Windows, the Python packages (shared), the files the Windows user can read. **Only upload code you trust, and never expose this API publicly.** The orchestrator itself is not authenticated.
- The role passwords are stored in `runs/projects/<id>/` (git-ignored, local only).

## How the checks and the repair work
- Before every try the app's tables are truncated (`RESTART IDENTITY CASCADE`), the seed SQL runs, every table `T` is copied to `initial_T`, and `ops_log` (one row per request: `endpoint` with a leading slash, `params` jsonb with all values, `status`) is recreated. Checks relate `initial_T`, `ops_log` and the final tables; the state shown in the dashboard is every table before and after, as JSON.
- Checks come from the AI and a **person approves** them; there is no built-in check. The filter drops checks that fire on one-at-a-time runs and marks checks that never fire as uninformative. Recall is not measured.
- **Making the race visible:** the test copy loads `controller/inject/sitecustomize.py`, which sleeps after each `SELECT` through psycopg2 (including dict cursors) and synchronous SQLAlchemy. asyncpg is covered too, with a non-blocking `asyncio.sleep` after `fetch`/`fetchrow`/`fetchval` (a blocking sleep would freeze the event loop and hide the race). psycopg 3 and async SQLAlchemy are not covered: on a slow or busy machine a race there may be rare, so use a larger burst (10 to 20 requests).
- **Repair** replaces the endpoint function (decorators kept) in a copy of the project; accepted only if (a) behaviour one request at a time matches the **original** (statuses of the burst and every table afterwards, ignoring columns that differ between two identical runs of the original, such as timestamps), (b) the failing schedule replays clean, (c) two batches of fresh simultaneous tries show no violation. The original goes through the same validation as a negative control. Uploaded files are never edited; the fix is shown as code to copy.

## Limits
- FastAPI + PostgreSQL; JSON, query and path values; one static header. No form/file bodies, cookie logins, WebSockets or token refresh.
- The static scan resolves names by simple rules; dynamic routing, `mount()` and generated routers are not understood (type the app and function by hand).
- One endpoint per setup. A fix replaces one function: a bug whose proper fix lives in another file can only be fixed if the AI can do it inside the handler.
- The schema and seed guesses are best-effort (SQLAlchemy models only; no SQLModel, no migrations). A seed with a small stock (such as 1) makes the race easy to hit.
- "Passed" is evidence, not proof.

## Samples and verification
`samples/` holds seven projects each with a `SETUP.md` (what to click and which values to enter); `python samples/verify.py` drives them through the real API (upload, scan, setup, test, a hand-written check, attack, delete) and `python samples/isolation_probe.py` runs the isolation probes. Recorded results are in `samples/RESULTS.md`.

## API (replaces the earlier `/projects` routes)
`POST /api/uploads` (multipart: `files`, optional `name`), `GET /api/uploads`, `GET /api/uploads/{id}`, `GET /api/uploads/{id}/source?path=&fn=`, `PUT /api/uploads/{id}/config`, `POST /api/uploads/{id}/check` (returns a job), `GET /api/uploads/{id}/jobs/{job}` (status, live log, result), `DELETE /api/uploads/{id}`. The project id is also the scenario id once set up (`/scenarios/{id}/...`).
