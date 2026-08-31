from __future__ import annotations
import re
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Product, ProductSlugRedirect

_TRANSLIT = str.maketrans({
    "а":"a","б":"b","в":"v","г":"h","ґ":"g","д":"d","е":"e","є":"ye","ж":"zh","з":"z","и":"y",
    "і":"i","ї":"yi","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s",
    "т":"t","у":"u","ф":"f","х":"kh","ц":"ts","ч":"ch","ш":"sh","щ":"shch","ь":"","ю":"yu",
    "я":"ya","ы":"y","э":"e","ё":"yo","ъ":"",
})
_EMPTY = {"none", "null", "nil", "n-a", "na", "undefined", "-", "—"}
_GENERIC = {
    "pidshypnyk","pidshypnyky","bearing","bearings","remin","remeni","belt","belts",
    "salnyk","salnyky","manzheta","seal","seals","mastilo","zmazhennya","lubricant","lubricants",
}

def clean_value(value: Any) -> str:
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return "" if text.casefold() in {"none","null","nil","n/a","na","undefined","-","—"} else text

def slugify(value: Any, max_length: int = 180) -> str:
    text = clean_value(value).lower().translate(_TRANSLIT)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    return text[:max_length].rstrip("-")

def _name_slug(value: str) -> str:
    tokens = [t for t in slugify(value).split("-") if t and t not in _EMPTY]
    while tokens and tokens[0] in _GENERIC:
        tokens.pop(0)
    return "-".join(tokens)

def make_product_slug(name: str, brand_name: str | None = None, manufacturer_code: str | None = None) -> str:
    parts: list[str] = []
    name_part = _name_slug(clean_value(name))
    if name_part:
        parts.append(name_part)
    brand = clean_value(brand_name)
    if brand and brand.casefold() != "без бренду":
        b = slugify(brand)
        if b and b not in "-".join(parts):
            parts.append(b)
    m = slugify(clean_value(manufacturer_code))
    if m and m not in "-".join(parts):
        parts.append(m)
    result = "-".join(x for x in parts if x and x not in _EMPTY)
    return result[:180].strip("-") or "product"

def make_unique_product_slug(
    db: Session, name: str, brand_name: str | None = None, manufacturer_code: str | None = None,
    *, product_id: int | None = None, requested_slug: str | None = None
) -> str:
    base = slugify(requested_slug) if clean_value(requested_slug) else make_product_slug(name, brand_name, manufacturer_code)
    base = base or "product"
    candidate, i = base, 2
    while True:
        existing = db.scalar(select(Product).where(Product.slug == candidate))
        if not existing or existing.id == product_id:
            return candidate
        candidate = f"{base}-{i}"
        i += 1

def remember_slug_redirect(db: Session, product: Product, old_slug: str | None) -> None:
    old_slug = slugify(old_slug)
    if not old_slug or old_slug == product.slug:
        return
    current = db.scalar(select(Product).where(Product.slug == old_slug))
    if current and current.id != product.id:
        return
    redirect = db.scalar(select(ProductSlugRedirect).where(ProductSlugRedirect.old_slug == old_slug))
    if redirect:
        redirect.product_id = product.id
    else:
        db.add(ProductSlugRedirect(product_id=product.id, old_slug=old_slug))

def has_bad_placeholder_slug(slug: str | None) -> bool:
    normalized = slugify(slug)
    return not normalized or bool(set(normalized.split("-")) & _EMPTY)
