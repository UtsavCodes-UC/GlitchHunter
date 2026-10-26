"""Demo target app: inventory. Deliberately racy in MODE=vuln, fixed in MODE=fixed.
The attacker (controller/) logs requests itself, so this app logs nothing and never touches ops_log / initial_state."""
import os
import time

import psycopg2.pool
from fastapi import FastAPI, Header, HTTPException

MODE = os.environ.get("MODE", "vuln")
if MODE not in {"vuln", "fixed"}:
    raise ValueError("MODE must be 'vuln' or 'fixed'")

pool = psycopg2.pool.ThreadedConnectionPool(5, 60, os.environ["GH_DATABASE_URL"])
app = FastAPI()


def hook(ms):  # test-only pause between the check and the write (vuln mode)
    if ms:
        time.sleep(ms / 1000)


class Conn:
    def __enter__(self):
        self.c = pool.getconn()
        return self.c

    def __exit__(self, *args):
        self.c.rollback()
        pool.putconn(self.c)


@app.post("/reset")
def reset(balance: int = 100, stock: int = 5):
    with Conn() as c:
        cur = c.cursor()
        cur.execute(
            "drop table if exists inventory;"
            "create table inventory(sku int primary key, stock int not null)"
        )
        cur.execute("insert into inventory values (1, %s)", (stock,))
        c.commit()
    return {"ok": True}


@app.post("/checkout")
def checkout(qty: int, x_race_delay: int = Header(0)):
    with Conn() as c:
        cur = c.cursor()
        if MODE == "vuln":
            cur.execute("select stock from inventory where sku=1")
            stock = cur.fetchone()[0]
            if stock < qty:
                raise HTTPException(409, "out of stock")
            hook(x_race_delay)
            cur.execute("update inventory set stock=%s where sku=1", (stock - qty,))
        else:
            cur.execute(
                "update inventory set stock=stock-%s where sku=1 and stock>=%s returning stock",
                (qty, qty),
            )
            if cur.fetchone() is None:
                raise HTTPException(409, "out of stock")
        c.commit()
    return {"ok": True}
# END-ENDPOINT


@app.get("/state")
def state():
    with Conn() as c:
        cur = c.cursor()
        cur.execute("select stock from inventory where sku=1")
        stock = cur.fetchone()[0]
    return {"stock": stock}
