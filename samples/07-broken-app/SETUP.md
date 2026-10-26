# Broken app (missing package + a file with a syntax error)

Nothing to attack: the scan warns about the unreadable file and the setup test fails with a clear message.

## How to use it
1. On the home page, **Your own code**: pick the folder `07-broken-app` (or drop it).
2. In the scan table the endpoint `POST /buy` should be labelled **writes / read-only**. Click **Use this** on it.
3. Check the setup form against the values below. Schema SQL / seed SQL: type them in as shown below.
4. **Save and test the setup**. The setup test should fail with a clear message naming the missing package. Nothing to attack.

## Setup values
| field | value |
|---|---|
| How to start the app | `main:app` |
| File / function | `api/main.py` / `buy` |
| Method and path | `POST /buy` |
| Other values are sent as | query |
| Requests sent together | `[{"qty": 1}, {"qty": 1}]` |
| Environment variable for the database | `DATABASE_URL` |
| Database URL style | `postgresql` |

Schema SQL:
```sql
CREATE TABLE t (id int);
```
Seed SQL:
```sql
-- (none)
```

Command line instead: `.\glitchhunter upload samples\07-broken-app` then `.\glitchhunter setup <id>` (uses the same suggested setup; the values above show what to change).
