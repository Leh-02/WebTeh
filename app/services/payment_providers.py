from __future__ import annotations

import os
from dataclasses import dataclass

from app.services import liqpay

try:
    from app.services import monobank
except Exception:  # Mono remains optional/secondary.
    monobank = None  # type: ignore[assignment]


@dataclass(frozen=True)
class PaymentProviderState:
    name: str
    configured: bool
    primary: bool


def primary_provider_name() -> str:
    value = os.getenv("PAYMENT_PROVIDER_PRIMARY", "liqpay").strip().lower()
    return value if value in {"liqpay", "monobank"} else "liqpay"


def secondary_provider_name() -> str:
    value = os.getenv("PAYMENT_PROVIDER_SECONDARY", "monobank").strip().lower()
    return value if value in {"liqpay", "monobank"} else "monobank"


def _mono_configured() -> bool:
    if monobank is None:
        return False
    for name in ("is_configured", "enabled", "is_enabled"):
        fn = getattr(monobank, name, None)
        if callable(fn):
            try:
                return bool(fn())
            except Exception:
                return False
    # Compatibility with the 2026-08-24 project where MONOBANK_TOKEN is env based.
    return bool(os.getenv("MONOBANK_TOKEN", "").strip())


def provider_is_configured(name: str) -> bool:
    name = name.lower()
    if name == "liqpay":
        return liqpay.is_configured()
    if name == "monobank":
        return _mono_configured()
    return False


def states() -> list[PaymentProviderState]:
    primary = primary_provider_name()
    order = [primary]
    secondary = secondary_provider_name()
    if secondary not in order:
        order.append(secondary)
    return [
        PaymentProviderState(
            name=name,
            configured=provider_is_configured(name),
            primary=(name == primary),
        )
        for name in order
    ]


def default_online_provider() -> str | None:
    """Return the first configured provider, preferring LiqPay by default."""
    for state in states():
        if state.configured:
            return state.name
    return None


def online_payment_available() -> bool:
    return default_online_provider() is not None
