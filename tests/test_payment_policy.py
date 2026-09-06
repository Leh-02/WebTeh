from decimal import Decimal
from types import SimpleNamespace

from app.services.payment_policy import payment_options


def product(require=None, cod=None, category_require=False, category_cod=True):
    return SimpleNamespace(
        require_prepayment_override=require,
        cod_allowed_override=cod,
        category=SimpleNamespace(require_prepayment=category_require, cod_allowed=category_cod),
    )


def settings():
    return SimpleNamespace(
        online_payment_enabled=True,
        bank_transfer_enabled=True,
        cod_enabled=True,
        cod_min_total=Decimal("500"),
    )


def option(items, value):
    return next(item for item in items if item["value"] == value)


def test_cod_is_enabled_above_threshold():
    items = payment_options(Decimal("1000"), settings(), monobank_ready=True, products=[product()])
    assert option(items, "cod")["enabled"] is True


def test_cod_stays_visible_but_disabled_below_threshold():
    items = payment_options(Decimal("499"), settings(), monobank_ready=True, products=[product()])
    cod = option(items, "cod")
    assert cod["enabled"] is False
    assert "500" in cod["reason"]


def test_prepayment_keeps_cod_visible_but_disabled():
    items = payment_options(Decimal("1000"), settings(), monobank_ready=True, products=[product(require=True)])
    cod = option(items, "cod")
    assert cod["enabled"] is False
    assert "передоплати" in cod["reason"]


def test_online_stays_visible_when_provider_is_not_ready():
    items = payment_options(Decimal("1000"), settings(), monobank_ready=False, products=[product()])
    online = option(items, "online")
    assert online["enabled"] is False


def test_bank_transfer_is_independent_from_online_provider():
    items = payment_options(Decimal("1000"), settings(), monobank_ready=False, products=[product()])
    assert option(items, "bank_transfer")["enabled"] is True
