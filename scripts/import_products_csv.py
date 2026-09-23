"""Import/update TopBearing products from UTF-8 CSV.

Required columns:
    sku,name,category,price

``category`` contains the Category.code value from the admin catalogue. For new
categories you may additionally provide category_name, parent_category and
product_type (bearings / belts / seals / lubricants / accessories / generic).

Core optional columns:
    brand,brand_country,manufacturer_code,alternative_markings,
    manufacturing_country,stock_qty,stock_is_tracked,availability_status,
    short_description,description,image_url,require_prepayment,cod_allowed,
    is_featured

Bearing optional columns:
    subtype,inner_diameter_mm,outer_diameter_mm,width_mm,rows,rolling_element,
    construction,series_type,cage_type,bearing_seal_type,clearance,precision_class

Belt optional columns:
    belt_type,profile,length_mm,belt_width_mm,ribs

Seal optional columns:
    seal_type,seal_inner_diameter_mm,seal_outer_diameter_mm,seal_width_mm,
    material,lip_type

Existing products keep their SEO slug unless --regenerate-slugs is used.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    BeltSpec,
    BearingSpec,
    Brand,
    Category,
    LubricantSpec,
    Product,
    ProductImage,
    SealSpec,
)
from app.services.catalog import normalize_belt_profile, normalize_category_code  # noqa: E402
from app.services.slug_service import make_unique_product_slug, remember_slug_redirect, slugify  # noqa: E402

EMPTY = {"", "none", "null", "n/a", "-", "—"}


def text(row, key):
    value = (row.get(key) or "").strip()
    return None if value.casefold() in EMPTY else value


def decimal(row, key, default=None):
    value = text(row, key)
    if value is None:
        return default
    try:
        return Decimal(value.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal {key}={value!r}") from exc


def integer(row, key, default=None):
    value = text(row, key)
    return default if value is None else int(value)


def boolean(row, key, default=None):
    value = text(row, key)
    if value is None:
        return default
    normalized = value.casefold()
    if normalized in {"1", "true", "yes", "y", "так"}:
        return True
    if normalized in {"0", "false", "no", "n", "ні"}:
        return False
    raise ValueError(f"Invalid boolean {key}={value!r}")


def normalize_code(value: str) -> str:
    code = slugify(value or "")
    code = re.sub(r"-+", "-", code).strip("-")
    return code[:64] or "category"


def get_category(db, row):
    raw_code = text(row, "category")
    if not raw_code:
        raise ValueError("category is required")
    code = raw_code.strip().lower()
    normalized_lookup = normalize_code(code)
    category = db.scalar(
        select(Category).where(func.lower(Category.code).in_({code, normalized_lookup}))
    )

    parent = None
    parent_code = text(row, "parent_category")
    if parent_code:
        parent = db.scalar(select(Category).where(func.lower(Category.code) == parent_code.strip().lower()))
        if not parent:
            raise ValueError(f"parent_category {parent_code!r} does not exist")

    requested_type = normalize_category_code(text(row, "product_type")) if text(row, "product_type") else None
    if category is None:
        if not text(row, "category_name") and not requested_type:
            raise ValueError(
                f"category {raw_code!r} does not exist. Create it in the admin panel first "
                "or provide category_name + product_type in the CSV"
            )
        inferred_type = requested_type
        if not inferred_type and parent:
            inferred_type = parent.product_type
        if not inferred_type:
            inferred_type = normalize_category_code(code)
        if inferred_type not in {"bearings", "belts", "seals", "lubricants", "accessories", "generic"}:
            inferred_type = "generic"
        category = Category(
            code=normalize_code(code),
            name=text(row, "category_name") or raw_code,
            parent_id=parent.id if parent else None,
            product_type=inferred_type,
            show_in_menu=True,
            is_active=True,
        )
        db.add(category)
        db.flush()
    else:
        if text(row, "category_name"):
            category.name = text(row, "category_name")
        if parent_code:
            category.parent_id = parent.id if parent else None
        if requested_type:
            category.product_type = requested_type

    prepayment = boolean(row, "category_require_prepayment", None)
    cod = boolean(row, "category_cod_allowed", None)
    if prepayment is not None:
        category.require_prepayment = prepayment
    if cod is not None:
        category.cod_allowed = cod
    return category


def get_brand(db, row):
    name = text(row, "brand")
    if not name or name.casefold() == "без бренду":
        return None
    brand = db.scalar(select(Brand).where(func.lower(Brand.name) == name.lower()))
    if not brand:
        base = slugify(name) or "brand"
        candidate, index = base, 2
        while db.scalar(select(Brand).where(Brand.slug == candidate)):
            candidate, index = f"{base}-{index}", index + 1
        brand = Brand(name=name, slug=candidate)
        db.add(brand)
        db.flush()
    country = text(row, "brand_country")
    if country:
        brand.country = country
    return brand


def apply_specs(product, category, row):
    kind = normalize_category_code(category.product_type) or "generic"
    # Keep exactly one type-specific specification family. This matters when a
    # SKU is moved to another category during a later import.
    if kind != "bearings" and product.bearing_spec is not None:
        product.bearing_spec = None
    if kind != "belts" and product.belt_spec is not None:
        product.belt_spec = None
    if kind != "seals" and product.seal_spec is not None:
        product.seal_spec = None
    if kind != "lubricants" and product.lubricant_spec is not None:
        product.lubricant_spec = None

    if kind == "bearings":
        spec = product.bearing_spec or BearingSpec(product_id=product.id)
        spec.subtype = text(row, "subtype")
        spec.inner_diameter_mm = decimal(row, "inner_diameter_mm")
        spec.outer_diameter_mm = decimal(row, "outer_diameter_mm")
        spec.width_mm = decimal(row, "width_mm")
        spec.rows = integer(row, "rows")
        spec.rolling_element = text(row, "rolling_element")
        spec.construction = text(row, "construction")
        spec.series_type = (text(row, "series_type") or "").upper() or None
        spec.cage_type = text(row, "cage_type")
        spec.seal_type = text(row, "bearing_seal_type") or text(row, "seal_type")
        spec.clearance = text(row, "clearance")
        spec.precision_class = text(row, "precision_class")
        product.bearing_spec = spec
    elif kind == "belts":
        spec = product.belt_spec or BeltSpec(product_id=product.id)
        spec.belt_type = text(row, "belt_type")
        spec.profile = normalize_belt_profile(text(row, "profile"))
        spec.length_mm = decimal(row, "length_mm")
        spec.width_mm = decimal(row, "belt_width_mm")
        spec.ribs = integer(row, "ribs")
        product.belt_spec = spec
    elif kind == "seals":
        spec = product.seal_spec or SealSpec(product_id=product.id)
        spec.seal_type = text(row, "seal_type")
        spec.inner_diameter_mm = decimal(row, "seal_inner_diameter_mm")
        spec.outer_diameter_mm = decimal(row, "seal_outer_diameter_mm")
        spec.width_mm = decimal(row, "seal_width_mm")
        # Material is retained as a specification even though it is not exposed
        # as a storefront filter.
        spec.material = text(row, "material")
        spec.lip_type = text(row, "lip_type")
        product.seal_spec = spec
    elif kind == "lubricants":
        spec = product.lubricant_spec or LubricantSpec(product_id=product.id)
        spec.lubricant_type = text(row, "lubricant_type")
        spec.viscosity = text(row, "viscosity")
        spec.base_type = text(row, "base_type")
        spec.package_size = text(row, "package_size")
        spec.temperature_range = text(row, "temperature_range")
        product.lubricant_spec = spec


def validate_required_specs(category, row):
    kind = normalize_category_code(category.product_type) or "generic"
    missing = []
    if kind == "bearings":
        for key in ("inner_diameter_mm", "outer_diameter_mm", "width_mm"):
            if decimal(row, key) is None:
                missing.append(key)
    elif kind == "belts":
        if not normalize_belt_profile(text(row, "profile")):
            missing.append("profile")
        if decimal(row, "length_mm") is None:
            missing.append("length_mm")
    elif kind == "seals":
        for key in ("seal_inner_diameter_mm", "seal_outer_diameter_mm", "seal_width_mm"):
            if decimal(row, key) is None:
                missing.append(key)
    if missing:
        raise ValueError(
            f"missing required {kind} specification fields: {', '.join(missing)}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("--regenerate-slugs", action="store_true")
    parser.add_argument(
        "--allow-incomplete-specs",
        action="store_true",
        help="Legacy escape hatch: import bearings/belts/seals even when required dimensions are missing",
    )
    args = parser.parse_args()
    created = updated = 0

    with SessionLocal() as db, Path(args.csv_path).open("r", encoding="utf-8-sig", newline="") as handle:
        for line_no, row in enumerate(csv.DictReader(handle), start=2):
            try:
                sku, name = text(row, "sku"), text(row, "name")
                if not sku or not name:
                    raise ValueError("sku and name are required")
                category = get_category(db, row)
                if not args.allow_incomplete_specs:
                    validate_required_specs(category, row)
                brand = get_brand(db, row)
                product = db.scalar(select(Product).where(Product.sku == sku))
                is_new = product is None
                if is_new:
                    product = Product(
                        sku=sku,
                        slug="temporary",
                        name=name,
                        category_id=category.id,
                        brand_id=brand.id if brand else None,
                        price=Decimal("0"),
                    )
                    db.add(product)
                    db.flush()
                    created += 1
                else:
                    updated += 1

                old_slug = product.slug
                product.name = name
                product.category_id = category.id
                product.brand_id = brand.id if brand else None
                product.manufacturer_code = text(row, "manufacturer_code")
                product.alternative_markings = text(row, "alternative_markings")
                product.manufacturing_country = text(row, "manufacturing_country")
                product.price = decimal(row, "price", Decimal("0")) or Decimal("0")
                product.stock_qty = max(0, integer(row, "stock_qty", 0) or 0)
                product.stock_is_tracked = bool(boolean(row, "stock_is_tracked", False))
                product.availability_status = text(row, "availability_status") or "in_stock"
                product.short_description = text(row, "short_description")
                product.description = text(row, "description")
                product.require_prepayment_override = boolean(row, "require_prepayment", None)
                product.cod_allowed_override = boolean(row, "cod_allowed", None)
                product.is_featured = bool(boolean(row, "is_featured", False))
                product.is_active = bool(boolean(row, "is_active", True))

                if is_new or args.regenerate_slugs:
                    product.slug = make_unique_product_slug(
                        db,
                        product.name,
                        brand.name if brand else None,
                        product.manufacturer_code,
                        product_id=product.id,
                    )
                    if not is_new and old_slug != product.slug:
                        remember_slug_redirect(db, product, old_slug)

                image = text(row, "image_url")
                if image and not product.images:
                    db.add(ProductImage(product_id=product.id, url=image, alt_text=product.name, sort_order=0, is_primary=True))

                apply_specs(product, category, row)
                db.flush()
            except Exception as exc:
                db.rollback()
                raise RuntimeError(f"CSV line {line_no}: {exc}") from exc
        db.commit()

    print(f"Created: {created}; updated: {updated}")


if __name__ == "__main__":
    main()
