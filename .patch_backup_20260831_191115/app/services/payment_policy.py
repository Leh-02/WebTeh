from decimal import Decimal

from app.models import StoreSettings


def payment_options(total: Decimal, settings: StoreSettings, *, monobank_ready: bool) -> list[dict[str, str]]:
    """Global payment policy.

    Per-category and per-product prepayment rules are intentionally ignored.
    COD is available only when the order reaches cod_min_total.
    """
    options: list[dict[str, str]] = []

    if settings.online_payment_enabled and monobank_ready:
        options.append({"value": "online", "label": "Оплата онлайн карткою"})

    if settings.bank_transfer_enabled:
        options.append({"value": "bank_transfer", "label": "Оплата за рахунком / безготівково"})

    threshold = Decimal(settings.cod_min_total or 0)
    if settings.cod_enabled and Decimal(total) >= threshold:
        options.append({"value": "cod", "label": "Післяплата при отриманні"})

    return options
