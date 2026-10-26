import os

import psycopg2
from fastapi import FastAPI

app = FastAPI(title="Likes")


@app.post("/posts/{post_id}/like")
def like(post_id: int):
    c = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        cur = c.cursor()
        cur.execute("select likes from posts where id = %s", (post_id,))
        likes = cur.fetchone()[0]
        cur.execute("update posts set likes = %s where id = %s", (likes + 1, post_id))
        c.commit()
        return {"likes": likes + 1}
    finally:
        c.close()
