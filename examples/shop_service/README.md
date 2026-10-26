# shop_service: a stand-in for a real third-party app

Written by us to look like what people publish: a package (`app/`), SQLAlchemy ORM models, a helper in `app/services/`, routers with a nested prefix (`/api/v1/orders`), a Pydantic JSON body, a required `Authorization` header, settings that need environment variables, `201` responses. The race is in `POST /api/v1/orders`: it reads the stock, checks it, then writes the new value.

It is NOT a real third-party project, so it shows that the upload handles this shape of app, not that it handles apps in general.

## Upload it
1. Zip the **contents of this folder except `setup.sql`** (so `app/` and `requirements.txt` are at the top of the zip).
2. Dashboard `/try`: name "Shop", choose the zip, paste `setup.sql`, open "Advanced": URL style `postgresql+psycopg2://`, extra variable `API_TOKEN=secret-token-123`. Upload and scan. Pick `POST /api/v1/orders`, type the header value `Bearer secret-token-123`, Create.
3. Step 2: ask the AI for checks and choose one. Then step 1 (attack) and step 3 (fix).

Command line equivalent (after zipping to `shop.zip`):
```powershell
.\glitchhunter upload --name "Shop" --app shop.zip --sql examples\shop_service\setup.sql --db-scheme postgresql+psycopg2 --env-var API_TOKEN=secret-token-123 --header "Authorization: Bearer secret-token-123"
```
Needs `sqlalchemy` installed (`pip install "sqlalchemy>=2.0"`) in the environment that runs GlitchHunter.
