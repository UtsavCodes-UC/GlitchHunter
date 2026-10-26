# Tickets (SQLAlchemy ORM, path + query values)

Four people book the last seat of a concert at the same moment.

## How to use it
1. On the home page, **Your own code**: pick the folder `02-tickets-sqlalchemy` (or drop it).
2. In the scan table the endpoint `POST /events/{event_id}/book` should be labelled **suspect**. Click **Use this** on it.
3. Check the setup form against the values below. Schema SQL and seed SQL are filled in automatically from `schema.sql`.
4. **Save and test the setup**. Run the attack: it should fail in most tries (more requests succeed than the data allows).

## Setup values
| field | value |
|---|---|
| How to start the app | `main:app` |
| File / function | `main.py` / `book` |
| Method and path | `POST /events/{event_id}/book` |
| Other values are sent as | query |
| Requests sent together | `[{"event_id": 1, "seats": 1}, {"event_id": 1, "seats": 1}, {"event_id": 1, "seats": 1}, {"event_id": 1, "seats": 1}]` |
| Environment variable for the database | `DATABASE_URL` |
| Database URL style | `postgresql+psycopg2` |

Schema SQL:
```sql
CREATE TABLE events (id serial PRIMARY KEY, name varchar(80) NOT NULL, seats_left int NOT NULL);
```
Seed SQL:
```sql
INSERT INTO events (name, seats_left) VALUES ('Concert', 1);
```

Command line instead: `.\glitchhunter upload samples\02-tickets-sqlalchemy` then `.\glitchhunter setup <id>` (uses the same suggested setup; the values above show what to change).
