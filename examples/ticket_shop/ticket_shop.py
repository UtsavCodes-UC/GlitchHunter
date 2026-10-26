"""Sample app for the "Try your own app" demo: a ticket shop with a classic race (read the seats left, check, then write).
Written in a different style from the demo apps on purpose (a new connection per request, DATABASE_URL, a different table)."""
import os

import psycopg2
from fastapi import FastAPI, HTTPException

app = FastAPI(title="Ticket shop")


def db():
    return psycopg2.connect(os.environ["DATABASE_URL"])


@app.get("/seats")
def seats():
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("select seats_left from seats where event_id = 1")
        return {"seats_left": cur.fetchone()[0]}
    finally:
        conn.close()


@app.post("/book")
def book(qty: int = 1):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("select seats_left from seats where event_id = 1")
        left = cur.fetchone()[0]
        if left < qty:
            raise HTTPException(409, "sold out")
        cur.execute("update seats set seats_left = %s where event_id = 1", (left - qty,))
        conn.commit()
        return {"booked": qty}
    finally:
        conn.close()
