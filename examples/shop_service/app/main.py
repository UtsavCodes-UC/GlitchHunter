from fastapi import APIRouter, FastAPI

from .config import SERVICE_NAME
from .routers import orders, products

app = FastAPI(title=SERVICE_NAME)

api = APIRouter(prefix="/api/v1")
api.include_router(products.router)
api.include_router(orders.router)
app.include_router(api)
