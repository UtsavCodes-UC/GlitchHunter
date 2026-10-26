from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .db import conn

app = FastAPI(title="Bank")


class Withdraw(BaseModel):
    account_id: int
    amount: int


@app.post("/withdraw")
def withdraw(w: Withdraw):
    c = conn()
    try:
        cur = c.cursor()
        cur.execute("select balance from accounts where id = %s", (w.account_id,))
        balance = cur.fetchone()[0]
        if balance < w.amount:
            raise HTTPException(409, "insufficient funds")
        cur.execute("update accounts set balance = %s where id = %s", (balance - w.amount, w.account_id))
        c.commit()
        return {"balance": balance - w.amount}
    finally:
        c.close()
