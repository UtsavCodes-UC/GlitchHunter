from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Product


def reserve_stock(db: Session, product_id: int, quantity: int) -> Product:
    """Take `quantity` units out of stock for an order."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if product is None:
        raise HTTPException(status_code=404, detail="no such product")
    if product.stock < quantity:
        raise HTTPException(status_code=409, detail="out of stock")
    product.stock = product.stock - quantity
    return product
