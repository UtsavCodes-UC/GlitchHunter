import os

import psycopg2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Transfers")


class Transfer(BaseModel):
    from_id: int
    to_id: int
    amount: int


@app.post("/transfer")
def transfer(t: Transfer):
    c = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        cur = c.cursor()
        cur.execute("select balance from accounts where id = %s", (t.from_id,))
        src = cur.fetchone()[0]
        cur.execute("select balance from accounts where id = %s", (t.to_id,))
        dst = cur.fetchone()[0]
        if src < t.amount:
            raise HTTPException(409, "insufficient funds")
        cur.execute("update accounts set balance = %s where id = %s", (src - t.amount, t.from_id))
        cur.execute("update accounts set balance = %s where id = %s", (dst + t.amount, t.to_id))
        c.commit()
        return {"ok": True}
    finally:
        c.close()
