import os

import psycopg2
from fastapi import FastAPI, HTTPException

app = FastAPI(title="Safe shop")


@app.post("/buy")
def buy(item_id: int = 1, qty: int = 1):
    c = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        cur = c.cursor()
        cur.execute("select stock from items where id = %s for update", (item_id,))
        stock = cur.fetchone()[0]
        if stock < qty:
            raise HTTPException(409, "sold out")
        cur.execute("update items set stock = stock - %s where id = %s", (qty, item_id))
        c.commit()
        return {"stock": stock - qty}
    finally:
        c.close()
