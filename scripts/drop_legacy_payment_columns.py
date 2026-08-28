"""Optional cleanup for obsolete per-category/per-product payment policy columns.

Run ONLY after a database backup and after the new application has been verified.
The 2026-08-24 app does not read these fields, so this cleanup is not required for normal use.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text

from app.database import engine

LEGACY_COLUMNS = {
    "categories": ["require_prepayment_default", "cod_allowed_default"],
    "products": ["require_prepayment_override", "cod_allowed_override"],
}


def main() -> None:
    if "--yes" not in sys.argv:
        print("Nothing changed. Back up the database, then run:")
        print("  python scripts/drop_legacy_payment_columns.py --yes")
        raise SystemExit(2)

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, wanted in LEGACY_COLUMNS.items():
            if table not in tables:
                continue
            existing = {column["name"] for column in inspect(engine).get_columns(table)}
            for column in wanted:
                if column not in existing:
                    continue
                conn.execute(text(f'ALTER TABLE "{table}" DROP COLUMN "{column}"'))
                print(f"Dropped {table}.{column}")
    print("Legacy payment-policy cleanup completed.")


if __name__ == "__main__":
    main()
