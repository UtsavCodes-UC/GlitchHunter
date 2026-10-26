import os

DATABASE_URL = os.environ["DATABASE_URL"]
API_TOKEN = os.environ["API_TOKEN"]
SERVICE_NAME = os.environ.get("SERVICE_NAME", "shop")
