import os
import psycopg2


def conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])
