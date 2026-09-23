"""Safely remove catalogue products while preserving order history.

Usage:
    python scripts/clear_catalog.py          # preview only
    python scripts/clear_catalog.py --yes    # perform deletion

OrderItem snapshots are kept; their product_id is set to NULL before products
are deleted. Categories, users, orders, store settings and audit logs remain.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import delete, func, select, update

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    BeltSpec,
    BearingSpec,
    Brand,
    LubricantSpec,
    OrderItem,
    Product,
    ProductImage,
    ProductSlugRedirect,
    SealSpec,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clear TopBearing catalogue without deleting orders")
    parser.add_argument("--yes", action="store_true", help="Actually delete the catalogue")
    parser.add_argument("--prune-brands", action="store_true", help="Also delete unused brands except 'Без бренду'")
    args = parser.parse_args()

    with SessionLocal() as db:
        product_count = db.scalar(select(func.count(Product.id))) or 0
        linked_order_items = db.scalar(
            select(func.count(OrderItem.id)).where(OrderItem.product_id.is_not(None))
        ) or 0
        image_count = db.scalar(select(func.count(ProductImage.id))) or 0

        print(f"Products: {product_count}")
        print(f"Product images in DB: {image_count}")
        print(f"Order items linked to products: {linked_order_items}")
        print("Orders and their SKU/name/price snapshots will be preserved.")

        if not args.yes:
            print("\nPreview only. Re-run with --yes after making a PostgreSQL backup.")
            return

        # Preserve historical orders while removing live Product rows.
        db.execute(update(OrderItem).where(OrderItem.product_id.is_not(None)).values(product_id=None))

        # Explicit child deletes also make the script safe on development SQLite
        # databases where foreign-key cascade enforcement may be disabled.
        for model in (ProductSlugRedirect, ProductImage, BearingSpec, BeltSpec, SealSpec, LubricantSpec):
            db.execute(delete(model))
        db.execute(delete(Product))

        if args.prune_brands:
            used_brand_ids = select(Product.brand_id).where(Product.brand_id.is_not(None))
            db.execute(
                delete(Brand).where(Brand.name != "Без бренду", Brand.id.not_in(used_brand_ids))
            )

        db.commit()
        print("Catalogue cleared successfully.")
        print("Categories, orders, users and settings were not deleted.")


if __name__ == "__main__":
    main()
