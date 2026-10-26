# Gift cards (asyncpg, async, creates its own table, reads DB_URL)

Three people redeem 30 each from a gift card holding 50. The app creates its own table, so the schema SQL stays empty.

## How to use it
1. On the home page, **Your own code**: pick the folder `03-giftcards-asyncpg` (or drop it).
2. In the scan table the endpoint `POST /giftcards/{code}/redeem` should be labelled **suspect**. Click **Use this** on it.
3. Check the setup form against the values below. Schema SQL / seed SQL: type them in as shown below.
4. **Save and test the setup**. Run the attack: it should fail in most tries (more requests succeed than the data allows).

## Setup values
| field | value |
|---|---|
| How to start the app | `server:app` |
| File / function | `server.py` / `redeem` |
| Method and path | `POST /giftcards/{code}/redeem` |
| Other values are sent as | json |
| Requests sent together | `[{"code": "GIFT50", "amount": 30}, {"code": "GIFT50", "amount": 30}, {"code": "GIFT50", "amount": 30}]` |
| Environment variable for the database | `DB_URL` |
| Database URL style | `postgresql` |

Schema SQL:
```sql
-- (empty: the app creates its own tables)
```
Seed SQL:
```sql
INSERT INTO giftcards VALUES ('GIFT50', 50);
```

Command line instead: `.\glitchhunter upload samples\03-giftcards-asyncpg` then `.\glitchhunter setup <id>` (uses the same suggested setup; the values above show what to change).
