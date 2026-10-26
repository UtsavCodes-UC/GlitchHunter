# Likes (a single .py file)

Four people like the same post at the same moment; every like must be counted.

## How to use it
1. On the home page, **Your own code**: pick the file `likes.py`.
2. In the scan table the endpoint `POST /posts/{post_id}/like` should be labelled **suspect**. Click **Use this** on it.
3. Check the setup form against the values below. Schema SQL / seed SQL: type them in as shown below.
4. **Save and test the setup**. Run the attack: it should fail in most tries (more requests succeed than the data allows).

## Setup values
| field | value |
|---|---|
| How to start the app | `likes:app` |
| File / function | `likes.py` / `like` |
| Method and path | `POST /posts/{post_id}/like` |
| Other values are sent as | query |
| Requests sent together | `[{"post_id": 1}, {"post_id": 1}, {"post_id": 1}, {"post_id": 1}]` |
| Environment variable for the database | `DATABASE_URL` |
| Database URL style | `postgresql` |

Schema SQL:
```sql
CREATE TABLE posts (id int PRIMARY KEY, likes int NOT NULL);
```
Seed SQL:
```sql
INSERT INTO posts VALUES (1, 0);
```

Command line instead: `.\glitchhunter upload samples\06-likes-single-file` then `.\glitchhunter setup <id>` (uses the same suggested setup; the values above show what to change).
