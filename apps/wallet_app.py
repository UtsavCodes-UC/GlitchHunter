import os
import time

import psycopg2.pool
from fastapi import FastAPI, Header, HTTPException

MODE = os.environ.get("MODE", "vuln")
if MODE not in {"vuln", "fixed"}:
    raise ValueError("MODE must be 'vuln' or 'fixed'")

pool = psycopg2.pool.ThreadedConnectionPool(
    5, 60, os.environ["GH_DATABASE_URL"]
)
app = FastAPI()


def hook(ms):
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
            "drop table if exists wallet;"
            "create table wallet(id int primary key, balance int not null)"
        )
        cur.execute("insert into wallet values (1, %s)", (balance,))
        c.commit()
    return {"ok": True}


@app.post("/withdraw")
def withdraw(amount: int, x_race_delay: int = Header(0)):
    with Conn() as c:
        cur = c.cursor()
        if MODE == "vuln":
            cur.execute("select balance from wallet where id=1")
            balance = cur.fetchone()[0]
            if balance < amount:
                raise HTTPException(409, "insufficient")
            hook(x_race_delay)
            cur.execute(
                "update wallet set balance=%s where id=1",
                (balance - amount,),
            )
        else:
            cur.execute(
                "update wallet set balance=balance-%s "
                "where id=1 and balance>=%s returning balance",
                (amount, amount),
            )
            if cur.fetchone() is None:
                raise HTTPException(409, "insufficient")
        c.commit()
    return {"ok": True}
# END-ENDPOINT


@app.get("/state")
def state():
    with Conn() as c:
        cur = c.cursor()
        cur.execute("select balance from wallet where id=1")
        balance = cur.fetchone()[0]
    return {"balance": balance}
