# Demo target apps

Run these commands from inside the `apps` folder. PostgreSQL 16 must be
available, and `GH_DATABASE_URL` must point to a database the app can use.
The URL below is the local example; replace it if your PostgreSQL settings
differ.

## Wallet

Vulnerable mode (port 8000):

```powershell
$env:GH_DATABASE_URL="postgresql://rh:rh@localhost:5432/rh"; $env:MODE="vuln"; python -m uvicorn wallet_app:app --port 8000
```

Fixed mode (port 8000):

```powershell
$env:GH_DATABASE_URL="postgresql://rh:rh@localhost:5432/rh"; $env:MODE="fixed"; python -m uvicorn wallet_app:app --port 8000
```

With the wallet app running, check its sequential and race behavior:

```powershell
python selfcheck.py http://127.0.0.1:8000
```

## Inventory

Vulnerable mode (port 8001):

```powershell
$env:GH_DATABASE_URL="postgresql://rh:rh@localhost:5432/rh"; $env:MODE="vuln"; python -m uvicorn inventory_app:app --port 8001
```

Fixed mode (port 8001):

```powershell
$env:GH_DATABASE_URL="postgresql://rh:rh@localhost:5432/rh"; $env:MODE="fixed"; python -m uvicorn inventory_app:app --port 8001
```
