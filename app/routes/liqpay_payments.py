from __future__ import annotations

import html
import os
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Order
from app.services import liqpay


router = APIRouter(tags=["payments"])


def _public_base_url(request: Request) -> str:
    configured = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    # Local fallback is useful for rendering/testing checkout only. LiqPay
    # callbacks require a public HTTPS URL in real operation.
    return str(request.base_url).rstrip("/")


def _find_order(db: Session, order_number: str) -> Order:
    order = db.query(Order).filter(Order.number == order_number).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def _autopost_form(action_url: str, data: str, signature: str) -> str:
    return f"""<!doctype html>
<html lang=\"uk\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
  <title>Перехід до оплати</title>
</head>
<body>
  <p>Переходимо до захищеної сторінки оплати…</p>
  <form id=\"liqpay-checkout\" method=\"post\" action=\"{html.escape(action_url, quote=True)}\">
    <input type=\"hidden\" name=\"data\" value=\"{html.escape(data, quote=True)}\">
    <input type=\"hidden\" name=\"signature\" value=\"{html.escape(signature, quote=True)}\">
    <noscript><button type=\"submit\">Продовжити оплату</button></noscript>
  </form>
  <script>document.getElementById('liqpay-checkout').submit();</script>
</body>
</html>"""


@router.get("/payments/liqpay/{order_number}", response_class=HTMLResponse)
def start_liqpay_payment(
    order_number: str,
    request: Request,
    db: Session = Depends(get_db),
):
    if not liqpay.is_configured():
        raise HTTPException(status_code=503, detail="LiqPay is not configured")

    order = _find_order(db, order_number)
    if getattr(order, "payment_status", None) == "paid":
        return RedirectResponse(url="/account", status_code=303)

    base = _public_base_url(request)
    checkout = liqpay.create_checkout(
        order_id=order.number,
        amount=order.total,
        description=f"Оплата замовлення TopBearing {order.number}",
        result_url=f"{base}/account",
        server_url=f"{base}/payments/liqpay/callback",
        customer_email=getattr(order, "email", None),
        customer_phone=getattr(order, "phone", None),
    )
    return HTMLResponse(
        _autopost_form(checkout.action_url, checkout.data, checkout.signature),
        headers={"Cache-Control": "no-store"},
    )


@router.post("/payments/liqpay/callback", response_class=PlainTextResponse)
def liqpay_callback(
    data: str = Form(...),
    signature: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        payload = liqpay.verify_and_decode_callback(data, signature)
    except (liqpay.LiqPaySignatureError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid LiqPay callback")

    order_number = str(payload.get("order_id", "")).strip()
    if not order_number:
        raise HTTPException(status_code=400, detail="Missing order_id")

    order = _find_order(db, order_number)

    if str(payload.get("currency", "")).upper() != "UAH":
        raise HTTPException(status_code=400, detail="Currency mismatch")

    try:
        callback_amount = Decimal(str(payload.get("amount"))).quantize(Decimal("0.01"))
        order_amount = Decimal(str(order.total)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        raise HTTPException(status_code=400, detail="Invalid amount")

    if callback_amount != order_amount:
        raise HTTPException(status_code=400, detail="Amount mismatch")

    mapped = liqpay.map_payment_status(str(payload.get("status", "")))
    if mapped is not None:
        current = getattr(order, "payment_status", None)
        # A delayed non-success callback must never downgrade a paid order.
        if current != "paid" or mapped in {"paid", "refunded"}:
            order.payment_status = mapped
            db.commit()

    return PlainTextResponse("ok")
