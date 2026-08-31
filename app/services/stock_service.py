from __future__ import annotations
import os
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from app.models import Order, Product

class InsufficientStock(RuntimeError):
    pass

def reservation_deadline() -> datetime:
    return datetime.utcnow() + timedelta(minutes=max(5, int(os.getenv("STOCK_RESERVATION_MINUTES", "30"))))

def reserve_product(db: Session, product_id: int, qty: int) -> Product:
    product = db.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if not product or not product.is_active:
        raise InsufficientStock("Товар недоступний.")
    if product.stock_is_tracked:
        if qty > product.stock_qty:
            raise InsufficientStock(f"Недостатня кількість товару: {product.name}.")
        product.stock_qty -= qty
        product.availability_status = "in_stock" if product.stock_qty > 0 else "out_of_stock"
    return product

def mark_new_order_stock(order: Order) -> None:
    order.stock_restored = False
    if order.payment_method == "online":
        order.stock_state = "reserved"
        order.stock_reserved_until = reservation_deadline()
    else:
        order.stock_state = "committed"
        order.stock_reserved_until = None

def release_order_stock(db: Session, order: Order) -> None:
    if order.stock_state == "released" or order.stock_restored:
        return
    for item in sorted(order.items, key=lambda x: x.product_id or 0):
        if not item.product_id:
            continue
        product = db.scalar(select(Product).where(Product.id == item.product_id).with_for_update())
        if product and product.stock_is_tracked:
            product.stock_qty += item.qty
            product.availability_status = "in_stock" if product.stock_qty > 0 else "out_of_stock"
    order.stock_state = "released"
    order.stock_restored = True
    order.stock_reserved_until = None

def re_reserve_order_stock(db: Session, order: Order) -> bool:
    if order.stock_state != "released" and not order.stock_restored:
        if order.stock_state == "reserved" and order.payment_status != "paid":
            order.stock_reserved_until = reservation_deadline()
        return True
    locked = []
    for item in sorted(order.items, key=lambda x: x.product_id or 0):
        if not item.product_id:
            continue
        product = db.scalar(select(Product).where(Product.id == item.product_id).with_for_update())
        if product and product.stock_is_tracked:
            if product.stock_qty < item.qty:
                return False
            locked.append((product, item.qty))
    for product, qty in locked:
        product.stock_qty -= qty
        product.availability_status = "in_stock" if product.stock_qty > 0 else "out_of_stock"
    order.stock_restored = False
    if order.payment_method == "online" and order.payment_status != "paid":
        order.stock_state = "reserved"
        order.stock_reserved_until = reservation_deadline()
    else:
        order.stock_state = "committed"
        order.stock_reserved_until = None
    return True

def sync_stock_after_payment(db: Session, order: Order) -> None:
    if order.payment_status == "paid":
        order.stock_state = "committed"
        order.stock_restored = False
        order.stock_reserved_until = None
    elif order.payment_status == "failed" and order.stock_state == "reserved":
        release_order_stock(db, order)

def release_expired_reservations(db: Session, *, limit: int = 100) -> int:
    now = datetime.utcnow()
    stmt = (
        select(Order)
        .where(
            Order.stock_state == "reserved",
            Order.stock_reserved_until.is_not(None),
            Order.stock_reserved_until < now,
            Order.payment_status != "paid",
        )
        .order_by(Order.stock_reserved_until)
        .limit(limit)
        .options(selectinload(Order.items))
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    orders = db.scalars(stmt).all()
    for order in orders:
        release_order_stock(db, order)
        if order.payment_status in {"pending", "unpaid"}:
            order.payment_status = "failed"
    return len(orders)
