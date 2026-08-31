from decimal import Decimal
from types import SimpleNamespace
from app.services.payment_policy import payment_options

def product(require=None, cod=None, category_require=False, category_cod=True):
    return SimpleNamespace(require_prepayment_override=require, cod_allowed_override=cod,
        category=SimpleNamespace(require_prepayment=category_require, cod_allowed=category_cod))

def settings():
    return SimpleNamespace(online_payment_enabled=True, bank_transfer_enabled=True, cod_enabled=True, cod_min_total=Decimal("500"))

def values(items): return {x["value"] for x in items}

def test_cod_normal():
    assert "cod" in values(payment_options(Decimal("1000"), settings(), monobank_ready=True, products=[product()]))

def test_prepayment_removes_cod():
    assert "cod" not in values(payment_options(Decimal("1000"), settings(), monobank_ready=True, products=[product(require=True)]))
