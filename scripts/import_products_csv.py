"""Import/update TopBearing products from UTF-8 CSV.

Core:
sku,name,category,brand,brand_country,manufacturer_code,alternative_markings,
manufacturing_country,price,stock_qty,stock_is_tracked,availability_status,
short_description,description,image_url,require_prepayment,cod_allowed

Category policy (optional):
category_require_prepayment,category_cod_allowed

Existing products keep their SEO slug unless --regenerate-slugs is used.
"""
from __future__ import annotations
import argparse, csv, sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models import BeltSpec, BearingSpec, Brand, Category, LubricantSpec, Product, ProductImage, SealSpec
from app.services.slug_service import make_unique_product_slug, remember_slug_redirect, slugify

EMPTY = {"", "none", "null", "n/a", "-", "—"}

def text(row, key):
    v = (row.get(key) or "").strip()
    return None if v.casefold() in EMPTY else v

def decimal(row, key, default=None):
    v = text(row, key)
    if v is None: return default
    try: return Decimal(v.replace(",", "."))
    except InvalidOperation as exc: raise ValueError(f"Invalid decimal {key}={v!r}") from exc

def integer(row, key, default=None):
    v = text(row, key)
    return default if v is None else int(v)

def boolean(row, key, default=None):
    v = text(row, key)
    if v is None: return default
    n = v.casefold()
    if n in {"1","true","yes","y","так"}: return True
    if n in {"0","false","no","n","ні"}: return False
    raise ValueError(f"Invalid boolean {key}={v!r}")

def get_category(db, row):
    code = (text(row, "category") or "").lower()
    if not code: raise ValueError("category is required")
    c = db.scalar(select(Category).where(Category.code == code))
    if not c:
        c = Category(code=code, name=code, is_active=True)
        db.add(c); db.flush()
    p, cod = boolean(row, "category_require_prepayment", None), boolean(row, "category_cod_allowed", None)
    if p is not None: c.require_prepayment = p
    if cod is not None: c.cod_allowed = cod
    return c

def get_brand(db, row):
    name = text(row, "brand") or "Без бренду"
    b = db.scalar(select(Brand).where(func.lower(Brand.name) == name.lower()))
    if not b:
        base, candidate, i = slugify(name) or "brand", slugify(name) or "brand", 2
        while db.scalar(select(Brand).where(Brand.slug == candidate)):
            candidate, i = f"{base}-{i}", i + 1
        b = Brand(name=name, slug=candidate)
        db.add(b); db.flush()
    if text(row, "brand_country"): b.country = text(row, "brand_country")
    return b

def apply_specs(p, row):
    code = p.category.code
    if code in {"bearing","bearings"}:
        s = p.bearing_spec or BearingSpec(product_id=p.id)
        s.subtype=text(row,"subtype"); s.inner_diameter_mm=decimal(row,"inner_diameter_mm")
        s.outer_diameter_mm=decimal(row,"outer_diameter_mm"); s.width_mm=decimal(row,"width_mm")
        s.rows=integer(row,"rows"); s.cage_type=text(row,"cage_type")
        s.seal_type=text(row,"bearing_seal_type") or text(row,"seal_type")
        s.clearance=text(row,"clearance"); s.precision_class=text(row,"precision_class"); p.bearing_spec=s
    elif code in {"belt","belts"}:
        s=p.belt_spec or BeltSpec(product_id=p.id); s.belt_type=text(row,"belt_type")
        s.profile=text(row,"profile"); s.length_mm=decimal(row,"length_mm"); s.width_mm=decimal(row,"belt_width_mm"); p.belt_spec=s
    elif code in {"seal","seals"}:
        s=p.seal_spec or SealSpec(product_id=p.id); s.seal_type=text(row,"seal_type")
        s.inner_diameter_mm=decimal(row,"seal_inner_diameter_mm"); s.outer_diameter_mm=decimal(row,"seal_outer_diameter_mm")
        s.width_mm=decimal(row,"seal_width_mm"); s.material=text(row,"material"); s.lip_type=text(row,"lip_type"); p.seal_spec=s
    elif code in {"lubricant","lubricants"}:
        s=p.lubricant_spec or LubricantSpec(product_id=p.id); s.lubricant_type=text(row,"lubricant_type")
        s.viscosity=text(row,"viscosity"); s.base_type=text(row,"base_type"); s.package_size=text(row,"package_size")
        s.temperature_range=text(row,"temperature_range"); p.lubricant_spec=s

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("csv_path"); parser.add_argument("--regenerate-slugs",action="store_true")
    args=parser.parse_args(); created=updated=0
    with SessionLocal() as db, Path(args.csv_path).open("r",encoding="utf-8-sig",newline="") as handle:
        for line_no,row in enumerate(csv.DictReader(handle),start=2):
            try:
                sku,name=text(row,"sku"),text(row,"name")
                if not sku or not name: raise ValueError("sku and name are required")
                c,b=get_category(db,row),get_brand(db,row)
                p=db.scalar(select(Product).where(Product.sku==sku)); is_new=p is None
                if is_new:
                    p=Product(sku=sku,slug="temporary",name=name,category_id=c.id,brand_id=b.id,price=Decimal("0"))
                    db.add(p); db.flush(); created+=1
                else: updated+=1
                old=p.slug; p.name=name; p.category_id=c.id; p.brand_id=b.id
                p.manufacturer_code=text(row,"manufacturer_code"); p.alternative_markings=text(row,"alternative_markings")
                p.manufacturing_country=text(row,"manufacturing_country"); p.price=decimal(row,"price",Decimal("0")) or Decimal("0")
                p.stock_qty=max(0,integer(row,"stock_qty",0) or 0); p.stock_is_tracked=bool(boolean(row,"stock_is_tracked",False))
                p.availability_status=text(row,"availability_status") or "in_stock"; p.short_description=text(row,"short_description")
                p.description=text(row,"description"); p.require_prepayment_override=boolean(row,"require_prepayment",None)
                p.cod_allowed_override=boolean(row,"cod_allowed",None); p.is_active=True
                if is_new or args.regenerate_slugs:
                    p.slug=make_unique_product_slug(db,p.name,b.name,p.manufacturer_code,product_id=p.id)
                    if not is_new and old != p.slug: remember_slug_redirect(db,p,old)
                image=text(row,"image_url")
                if image and not p.images:
                    db.add(ProductImage(product_id=p.id,url=image,alt_text=p.name,sort_order=0,is_primary=True))
                apply_specs(p,row); db.flush()
            except Exception as exc:
                db.rollback(); raise RuntimeError(f"CSV line {line_no}: {exc}") from exc
        db.commit()
    print(f"Created: {created}; updated: {updated}")

if __name__=="__main__":
    main()
