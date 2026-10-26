import notinstalled_pkg  # not installed anywhere: the app cannot start
from fastapi import FastAPI

app = FastAPI(title="Broken")


@app.post("/buy")
def buy(qty: int = 1):
    return {"ok": notinstalled_pkg.go(qty)}
