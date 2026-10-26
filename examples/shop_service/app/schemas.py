from pydantic import BaseModel, Field


class OrderCreate(BaseModel):
    product_id: int
    quantity: int = Field(ge=1, le=10)
    note: str | None = None


class ProductOut(BaseModel):
    id: int
    name: str
    stock: int
