from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Order
from ..schemas import OrderCreate
from ..security import require_token
from ..services.inventory import reserve_stock

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", status_code=201)
def create_order(payload: OrderCreate, db: Session = Depends(get_db), _: str = Depends(require_token)):
    product = reserve_stock(db, payload.product_id, payload.quantity)
    order = Order(product_id=product.id, quantity=payload.quantity)
    db.add(order)
    db.commit()
    return {"order_id": order.id, "remaining": product.stock}
