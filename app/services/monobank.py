from __future__ import annotations

import base64
import json
import os
from decimal import Decimal, ROUND_HALF_UP

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

API_BASE = "https://api.monobank.ua"
_PUBKEY = None


def configured() -> bool:
    return bool(os.getenv("MONOBANK_TOKEN", "").strip())


def _headers() -> dict[str, str]:
    token = os.getenv("MONOBANK_TOKEN", "").strip()
    if not token:
        raise RuntimeError("MONOBANK_TOKEN is not configured")
    return {"X-Token": token, "X-Cms": "TopBearing", "X-Cms-Version": "2026.08.24"}


def _kopecks(value: Decimal) -> int:
    return int((Decimal(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def create_invoice(*, order, redirect_url: str | None, webhook_url: str | None) -> dict:
    payload = {
        "amount": _kopecks(order.total),
        "ccy": 980,
        "merchantPaymInfo": {
            "reference": order.number,
            "destination": f"Оплата замовлення TopBearing {order.number}",
            "comment": f"Замовлення {order.number}",
        },
        "paymentType": "debit",
        "validity": 86400,
    }
    if redirect_url:
        payload["redirectUrl"] = redirect_url
    if webhook_url:
        payload["webHookUrl"] = webhook_url

    with httpx.Client(timeout=20) as client:
        response = client.post(f"{API_BASE}/api/merchant/invoice/create", headers=_headers(), json=payload)
        response.raise_for_status()
        data = response.json()
    if not data.get("invoiceId") or not data.get("pageUrl"):
        raise RuntimeError("Monobank returned an incomplete invoice response")
    return data


def invoice_status(invoice_id: str) -> dict:
    with httpx.Client(timeout=20) as client:
        response = client.get(
            f"{API_BASE}/api/merchant/invoice/status",
            headers=_headers(),
            params={"invoiceId": invoice_id},
        )
        response.raise_for_status()
        return response.json()


def _public_key():
    global _PUBKEY
    if _PUBKEY is not None:
        return _PUBKEY
    with httpx.Client(timeout=20) as client:
        response = client.get(f"{API_BASE}/api/merchant/pubkey", headers=_headers())
        response.raise_for_status()
        encoded = response.json()["key"]
    pem = base64.b64decode(encoded)
    _PUBKEY = serialization.load_pem_public_key(pem)
    return _PUBKEY


def verify_webhook(raw_body: bytes, x_sign: str | None) -> bool:
    if not x_sign or not configured():
        return False
    try:
        signature = base64.b64decode(x_sign)
        key = _public_key()
        key.verify(signature, raw_body, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, TypeError, httpx.HTTPError):
        return False


def parse_webhook(raw_body: bytes) -> dict:
    return json.loads(raw_body.decode("utf-8"))
