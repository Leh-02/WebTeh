from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LIQPAY_CHECKOUT_URL = "https://www.liqpay.ua/api/3/checkout"
LIQPAY_API_URL = "https://www.liqpay.ua/api/request"
LIQPAY_API_VERSION = 7


class LiqPayError(RuntimeError):
    pass


@dataclass(frozen=True)
class LiqPayCheckout:
    action_url: str
    data: str
    signature: str


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def public_key() -> str:
    return _env("LIQPAY_PUBLIC_KEY")


def private_key() -> str:
    return _env("LIQPAY_PRIVATE_KEY")


def configured() -> bool:
    return bool(public_key() and private_key())


def is_configured() -> bool:
    """Backward-compatible alias used by payment_providers.py."""
    return configured()


def _require_configured() -> None:
    if not configured():
        raise LiqPayError("Set LIQPAY_PUBLIC_KEY and LIQPAY_PRIVATE_KEY")


def _amount(value: Decimal | int | float | str) -> str:
    result = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if result <= 0:
        raise ValueError("Payment amount must be positive")
    return format(result, ".2f")


def _encode(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _signature(data: str) -> str:
    _require_configured()
    raw = (private_key() + data + private_key()).encode("utf-8")
    return base64.b64encode(hashlib.sha3_256(raw).digest()).decode("ascii")


def _decode(data: str) -> dict[str, Any]:
    try:
        decoded = json.loads(base64.b64decode(data, validate=True).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiqPayError("Invalid LiqPay data") from exc
    if not isinstance(decoded, dict):
        raise LiqPayError("Invalid LiqPay payload")
    return decoded


def verify_and_decode_callback(data: str, signature: str) -> dict[str, Any]:
    if not data or not signature or not configured():
        raise LiqPayError("Invalid LiqPay callback")
    expected = _signature(data)
    if not hmac.compare_digest(expected, signature):
        raise LiqPayError("Invalid LiqPay signature")
    payload = _decode(data)
    if str(payload.get("public_key", "")) != public_key():
        raise LiqPayError("LiqPay public key mismatch")
    return payload


def create_checkout(
    *,
    order_id: str,
    amount: Decimal | int | float | str,
    description: str,
    result_url: str,
    server_url: str,
) -> LiqPayCheckout:
    _require_configured()
    order_id = str(order_id).strip()
    if not order_id or len(order_id) > 255:
        raise ValueError("Invalid order_id")

    payload: dict[str, Any] = {
        "version": LIQPAY_API_VERSION,
        "public_key": public_key(),
        "action": "pay",
        "amount": _amount(amount),
        "currency": "UAH",
        "description": str(description)[:255],
        "order_id": order_id,
        "language": "uk",
        "paytypes": "card,apay,gpay,privat24",
        "result_url": result_url,
        "server_url": server_url,
    }
    data = _encode(payload)
    return LiqPayCheckout(LIQPAY_CHECKOUT_URL, data, _signature(data))


def _api_request(payload: Mapping[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    _require_configured()
    request_payload = dict(payload)
    request_payload.setdefault("version", LIQPAY_API_VERSION)
    request_payload.setdefault("public_key", public_key())
    data = _encode(request_payload)
    body = urlencode({"data": data, "signature": _signature(data)}).encode("ascii")
    request = Request(
        LIQPAY_API_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "TopBearing/1.0"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise LiqPayError("LiqPay API request failed") from exc
    if not isinstance(result, dict):
        raise LiqPayError("Invalid LiqPay API response")
    return result


def payment_status(order_id: str) -> dict[str, Any]:
    return _api_request({"action": "status", "order_id": str(order_id)})


def refund_payment(order_id: str, amount: Decimal | int | float | str) -> dict[str, Any]:
    """Request a refund for an existing LiqPay order."""
    order_id = str(order_id).strip()
    if not order_id or len(order_id) > 255:
        raise ValueError("Invalid order_id")

    result = _api_request(
        {
            "action": "refund",
            "order_id": order_id,
            "amount": _amount(amount),
        }
    )
    if str(result.get("result", "")).strip().lower() == "error":
        description = str(
            result.get("err_description")
            or result.get("err_code")
            or "LiqPay refund failed"
        )
        raise LiqPayError(description)
    return result


def map_payment_status(status: str | None) -> str | None:
    value = (status or "").strip().lower()
    if value == "success":
        return "paid"
    if value == "reversed":
        return "refunded"
    if value in {"failure", "error"}:
        return "failed"
    if value:
        return "pending"
    return None
