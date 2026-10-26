# Transfers (four DIFFERENT requests in one burst)

Four different transfers between three accounts arrive together; the total money must stay the same.

## How to use it
1. On the home page, **Your own code**: pick the folder `04-transfer-two-accounts` (or drop it).
2. In the scan table the endpoint `POST /transfer` should be labelled **suspect**. Click **Use this** on it.
3. Check the setup form against the values below. Schema SQL and seed SQL are filled in automatically from `schema.sql`.
4. **Save and test the setup**. Run the attack: it should fail in most tries (more requests succeed than the data allows).

## Setup values
| field | value |
|---|---|
| How to start the app | `main:app` |
| File / function | `main.py` / `transfer` |
| Method and path | `POST /transfer` |
| Other values are sent as | json |
| Requests sent together | `[{"from_id": 1, "to_id": 2, "amount": 80}, {"from_id": 1, "to_id": 3, "amount": 80}, {"from_id": 2, "to_id": 1, "amount": 10}, {"from_id": 3, "to_id": 1, "amount": 5}]` |
| Environment variable for the database | `DATABASE_URL` |
| Database URL style | `postgresql` |

Schema SQL:
```sql
CREATE TABLE accounts (id int PRIMARY KEY, balance int NOT NULL);
```
Seed SQL:
```sql
INSERT INTO accounts VALUES (1, 100), (2, 50), (3, 50);
```

Command line instead: `.\glitchhunter upload samples\04-transfer-two-accounts` then `.\glitchhunter setup <id>` (uses the same suggested setup; the values above show what to change).
