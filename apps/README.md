# Demo target apps

Deliberately racy FastAPI + PostgreSQL apps that GlitchHunter attacks. Run every command from inside the `apps` folder.
PostgreSQL 16 must be running and `GH_DATABASE_URL` must point to a database the app can use (database `rh` and user `rh` from the setup notes):

```powershell
$env:GH_DATABASE_URL="postgresql://rh:rh@localhost:5432/rh"
```

The apps log nothing and never touch `ops_log` / `initial_state`: the attacker records requests itself.

## Contract (see docs/contracts.md)
- `POST /reset?balance=<int>&stock=<int>` recreates only the app's own table and sets the starting value.
- Wallet: `POST /withdraw?amount=<int>` returns 200 or 409 (insufficient). `GET /state` returns `{"balance": n}`.
- Inventory: `POST /checkout?qty=<int>` returns 200 or 409 (out of stock). `GET /state` returns `{"stock": n}`.
- Optional test-only header `X-Race-Delay: <ms>` pauses between check and write (vuln mode only).
- Each endpoint function runs from its `@app.post(...)` line to a `# END-ENDPOINT` line. The repair tool replaces the text between them, so keep both modes inside that one function.

## Wallet (port 8000)

Vulnerable:

```powershell
$env:MODE="vuln"; python -m uvicorn wallet_app:app --port 8000
```

Fixed:

```powershell
$env:MODE="fixed"; python -m uvicorn wallet_app:app --port 8000
```

Check it (sequential tests, then 20 simultaneous pairs):

```powershell
python selfcheck.py http://127.0.0.1:8000
```

## Inventory (port 8001)

Vulnerable:

```powershell
$env:MODE="vuln"; python -m uvicorn inventory_app:app --port 8001
```

Fixed:

```powershell
$env:MODE="fixed"; python -m uvicorn inventory_app:app --port 8001
```

```powershell
python selfcheck.py http://127.0.0.1:8001 --scenario inventory
```
