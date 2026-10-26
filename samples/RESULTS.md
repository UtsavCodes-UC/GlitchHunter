# Recorded results (second full run, Windows 11, PostgreSQL 16.2, a non-superuser server role with CREATEROLE)

Command: `python samples/verify.py` against a freshly started API (hand-written checks, 20 attack trials per sample, no AI key needed).

| sample | what it tests | scan hint | setup test | violations in 20 tries | result |
|---|---|---|---|---|---|
| 01-bank-psycopg2 | psycopg2, package layout, JSON body | looks risky | ok | 19 | PASS |
| 02-tickets-sqlalchemy | SQLAlchemy ORM, path + query values | looks risky | ok | 20 | PASS |
| 03-giftcards-asyncpg | asyncpg (async), creates its own table, reads `DB_URL` | looks risky | ok | 20 | PASS |
| 04-transfer-two-accounts | four DIFFERENT requests in one burst | looks risky | ok | 17 | PASS |
| 05-safe-shop | correct `SELECT ... FOR UPDATE` app | guarded | ok | 0 (no false alarm) | PASS |
| 06-likes-single-file | one `.py` file uploaded | looks risky | ok | 20 | PASS |
| 07-broken-app | missing package and a file with a syntax error | scan warns about `helpers.py` | setup error naming `notinstalled_pkg` | not attacked | PASS |

Each run also deleted its project and checked that the project and its database role were gone.
Counts vary from run to run because a race is probabilistic. The samples are small stand-ins written by us, not real third-party apps.

`python samples/isolation_probe.py` (with a fake `GEMINI_API_KEY` set in the environment): every probe was denied except creating a table in the project's own schema, and the app saw no key or main database URL. The Linux/macOS process limits, the unprivileged-user switch and the Docker `/proc/1/environ` check were NOT run (no Docker or WSL on this machine).

Not checked here: the dashboard flow was clicked through once in the built-in browser (upload of a single file, setup, live log, attack: 37 of 50 tries failed, tables shown before and after); drag-and-drop of a folder and the zip picker were not exercised.
