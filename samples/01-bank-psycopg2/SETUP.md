# Bank (psycopg2, package layout, JSON body)

Three people withdraw 80 from an account holding 100 at the same moment.

## How to use it
1. On the home page, **Your own code**: pick the folder `01-bank-psycopg2` (or drop it).
2. In the scan table the endpoint `POST /withdraw` should be labelled **suspect**. Click **Use this** on it.
3. Check the setup form against the values below. Schema SQL and seed SQL are filled in automatically from `schema.sql`.
4. **Save and test the setup**. Run the attack: it should fail in most tries (more requests succeed than the data allows).

## Setup values
| field | value |
|---|---|
| How to start the app | `app.main:app` |
| File / function | `app/main.py` / `withdraw` |
| Method and path | `POST /withdraw` |
| Other values are sent as | json |
| Requests sent together | `[{"account_id": 1, "amount": 80}, {"account_id": 1, "amount": 80}, {"account_id": 1, "amount": 80}]` |
| Environment variable for the database | `DATABASE_URL` |
| Database URL style | `postgresql` |

Schema SQL:
```sql
CREATE TABLE accounts (id int PRIMARY KEY, balance int NOT NULL);
```
Seed SQL:
```sql
INSERT INTO accounts VALUES (1, 100);
```

Command line instead: `.\glitchhunter upload samples\01-bank-psycopg2` then `.\glitchhunter setup <id>` (uses the same suggested setup; the values above show what to change).
