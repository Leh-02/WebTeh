from __future__ import annotations

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import add_mapped_attribute, mapped_column

from .models import Brand, Order, Product


def _add_if_missing(model, name: str, column) -> None:
    if not hasattr(model, name):
        add_mapped_attribute(model, name, column)


_add_if_missing(Brand, "country", mapped_column(String(120), nullable=True))
_add_if_missing(Product, "alternative_markings", mapped_column(Text, nullable=True))
_add_if_missing(Product, "manufacturing_country", mapped_column(String(120), nullable=True))
_add_if_missing(Order, "payment_provider", mapped_column(String(32), nullable=True))
_add_if_missing(Order, "paid_at", mapped_column(DateTime, nullable=True))
_add_if_missing(Order, "refunded_at", mapped_column(DateTime, nullable=True))
