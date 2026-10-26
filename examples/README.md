# Example apps for "Try your own app"

`ticket_shop/` is a small FastAPI + psycopg2 app with a deliberate race in `POST /book`.

On the dashboard's `/try` page: name it "Ticket shop", choose `examples/ticket_shop/ticket_shop.py`, paste `examples/ticket_shop/setup.sql` (or click "Use the example setup SQL"), keep the environment variable `DATABASE_URL`, then Upload and scan. Pick `POST /book`, values `{"qty": 1}`, 6 simultaneous requests, watch `seats` / `seats_left`.

Do not run `ticket_shop.py` yourself: GlitchHunter starts its own test copy with a private database schema.
Limits and safety notes: `docs/try_your_own_app.md`.
