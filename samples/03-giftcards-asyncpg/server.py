import os
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

pool = None


@asynccontextmanager
async def lifespan(app):
    global pool
    pool = await asyncpg.create_pool(os.environ["DB_URL"], min_size=2, max_size=10)
    await pool.execute("create table if not exists giftcards(code text primary key, balance int not null)")
    yield
    await pool.close()


app = FastAPI(title="Gift cards", lifespan=lifespan)


class Redeem(BaseModel):
    amount: int


@app.post("/giftcards/{code}/redeem")
async def redeem(code: str, body: Redeem):
    async with pool.acquire() as c:
        balance = await c.fetchval("select balance from giftcards where code = $1", code)
        if balance is None or balance < body.amount:
            raise HTTPException(409, "not enough balance")
        await c.execute("update giftcards set balance = $1 where code = $2", balance - body.amount, code)
    return {"balance": balance - body.amount}
