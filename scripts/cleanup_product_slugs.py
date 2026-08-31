"""Preview/apply safe product slug cleanup with 301 redirects."""
from __future__ import annotations
import argparse, sys
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import selectinload

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models import Product
from app.services.slug_service import has_bad_placeholder_slug, make_unique_product_slug, remember_slug_redirect

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        products = db.scalars(select(Product).order_by(Product.id).options(selectinload(Product.brand))).all()
        changed = 0
        for product in products:
            if not args.all and not has_bad_placeholder_slug(product.slug):
                continue
            new_slug = make_unique_product_slug(
                db, product.name, product.brand.name if product.brand else None,
                product.manufacturer_code, product_id=product.id
            )
            if new_slug == product.slug:
                continue
            print(f"{product.id}: /product/{product.slug} -> /product/{new_slug}")
            changed += 1
            if args.apply:
                old = product.slug
                product.slug = new_slug
                remember_slug_redirect(db, product, old)
        if args.apply:
            db.commit()
            print(f"Applied: {changed} change(s)")
        else:
            db.rollback()
            print(f"Preview only: {changed} change(s). Add --apply to save.")

if __name__ == "__main__":
    main()
