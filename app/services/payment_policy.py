from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from app.models import Product, StoreSettings


def _resolved_rules(product: Product) -> tuple[bool, bool]:
    category = product.category
    require = (
        product.require_prepayment_override
        if product.require_prepayment_override is not None
        else bool(getattr(category, "require_prepayment", False))
    )
    cod = (
        product.cod_allowed_override
        if product.cod_allowed_override is not None
        else bool(getattr(category, "cod_allowed", True))
    )
    return bool(require), bool(cod)


def payment_options(
    total: Decimal,
    settings: StoreSettings,
    *,
    monobank_ready: bool,
    products: Iterable[Product] = (),
) -> list[dict[str, Any]]:
    """Return configured payment methods together with their availability.

    The storefront intentionally keeps a configured method visible even when it is
    temporarily unavailable. This lets the customer understand the rule instead of
    seeing payment choices appear/disappear as the cart total changes.

    ``monobank_ready`` is retained as the keyword name for backwards compatibility;
    the caller passes readiness of the currently configured online provider (LiqPay
    first, Monobank fallback).
    """
    products = list(products)
    rules = [_resolved_rules(p) for p in products]
    requires_prepayment = any(require for require, _ in rules)
    all_allow_cod = all(cod for _, cod in rules) if rules else True
    total = Decimal(total)

    options: list[dict[str, Any]] = []

    if settings.online_payment_enabled:
        options.append(
            {
                "value": "online",
                "label": "Оплата онлайн карткою",
                "enabled": bool(monobank_ready),
                "reason": None if monobank_ready else "Онлайн-оплата тимчасово недоступна.",
            }
        )

    if settings.bank_transfer_enabled:
        options.append(
            {
                "value": "bank_transfer",
                "label": "Оплата за рахунком / безготівково",
                "enabled": True,
                "reason": None,
            }
        )

    if settings.cod_enabled:
        threshold = Decimal(settings.cod_min_total or 0)
        cod_enabled = True
        reason: str | None = None
        if requires_prepayment:
            cod_enabled = False
            reason = "Недоступно: один із товарів у замовленні потребує передоплати."
        elif not all_allow_cod:
            cod_enabled = False
            reason = "Недоступно для одного або кількох товарів у кошику."
        elif total < threshold:
            cod_enabled = False
            reason = f"Доступно для замовлень від {threshold:.0f} грн."

        options.append(
            {
                "value": "cod",
                "label": "Післяплата при отриманні",
                "enabled": cod_enabled,
                "reason": reason,
            }
        )

    return options
