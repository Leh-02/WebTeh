from decimal import Decimal
from collections.abc import Iterable
from app.models import Product, StoreSettings

def _resolved_rules(product: Product) -> tuple[bool, bool]:
    category = product.category
    require = product.require_prepayment_override if product.require_prepayment_override is not None else bool(getattr(category, "require_prepayment", False))
    cod = product.cod_allowed_override if product.cod_allowed_override is not None else bool(getattr(category, "cod_allowed", True))
    return bool(require), bool(cod)

def payment_options(
    total: Decimal, settings: StoreSettings, *, monobank_ready: bool, products: Iterable[Product] = ()
) -> list[dict[str, str]]:
    products = list(products)
    rules = [_resolved_rules(p) for p in products]
    requires_prepayment = any(x[0] for x in rules)
    all_allow_cod = all(x[1] for x in rules) if rules else True

    options: list[dict[str, str]] = []
    if settings.online_payment_enabled and monobank_ready:
        options.append({"value": "online", "label": "Оплата онлайн карткою"})
    if settings.bank_transfer_enabled:
        options.append({"value": "bank_transfer", "label": "Оплата за рахунком / безготівково"})
    threshold = Decimal(settings.cod_min_total or 0)
    if settings.cod_enabled and not requires_prepayment and all_allow_cod and Decimal(total) >= threshold:
        options.append({"value": "cod", "label": "Післяплата при отриманні"})
    return options
