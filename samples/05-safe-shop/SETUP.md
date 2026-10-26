# Safe shop (CORRECT: SELECT ... FOR UPDATE)

A correct app: the scan says guarded and the attack must find nothing (no false alarm).

## How to use it
1. On the home page, **Your own code**: pick the folder `05-safe-shop` (or drop it).
2. In the scan table the endpoint `POST /buy` should be labelled **guarded**. Click **Use this** on it.
3. Check the setup form against the values below. Schema SQL and seed SQL are filled in automatically from `schema.sql`.
4. **Save and test the setup**. Run the attack: it should NOT fail. The scan hint is `guarded` and no check fires.

## Setup values
| field | value |
|---|---|
| How to start the app | `main:app` |
| File / function | `main.py` / `buy` |
| Method and path | `POST /buy` |
| Other values are sent as | query |
| Requests sent together | `[{"item_id": 1, "qty": 1}, {"item_id": 1, "qty": 1}, {"item_id": 1, "qty": 1}, {"item_id": 1, "qty": 1}]` |
| Environment variable for the database | `DATABASE_URL` |
| Database URL style | `postgresql` |

Schema SQL:
```sql
CREATE TABLE items (id int PRIMARY KEY, stock int NOT NULL);
```
Seed SQL:
```sql
INSERT INTO items VALUES (1, 1);
```

Command line instead: `.\glitchhunter upload samples\05-safe-shop` then `.\glitchhunter setup <id>` (uses the same suggested setup; the values above show what to change).
