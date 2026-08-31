"""Small compatibility migration for the 2026-08-24 TopBearing update.

It deliberately only ADDS fields/tables. Legacy payment-policy columns are left in place so
existing SQLite/PostgreSQL databases are not destructively rebuilt. The application ignores them.
"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def _type_sql(dialect: str, generic: str) -> str:
    if dialect == "postgresql":
        generic = generic.replace("DATETIME", "TIMESTAMP")
        generic = generic.replace("BOOLEAN DEFAULT 1", "BOOLEAN DEFAULT TRUE")
        generic = generic.replace("BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT FALSE")
    return generic


def ensure_schema_20260824(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    dialect = engine.dialect.name

    additions: dict[str, dict[str, str]] = {
        "users": {
            "full_name": "VARCHAR(160)",
            "phone": "VARCHAR(40)",
            "created_at": "DATETIME",
        },
        "categories": {
            "name": "VARCHAR(120)",
            "description": "TEXT",
            "is_active": "BOOLEAN DEFAULT 1",
            "sort_order": "INTEGER DEFAULT 100",
        },
        "products": {
            "manufacturer_code": "VARCHAR(120)",
            "short_description": "VARCHAR(500)",
            "description": "TEXT",
            "stock_is_tracked": "BOOLEAN DEFAULT 0",
            "availability_status": "VARCHAR(32) DEFAULT 'in_stock'",
            "created_at": "DATETIME",
            "updated_at": "DATETIME",
        },
        "product_images": {
            "url": "VARCHAR(600)",
            "alt_text": "VARCHAR(220)",
            "sort_order": "INTEGER DEFAULT 0",
            "is_primary": "BOOLEAN DEFAULT 0",
        },
        "orders": {
            "payment_method": "VARCHAR(32)",
            "stock_restored": "BOOLEAN DEFAULT 0",
            "customer_name": "VARCHAR(160)",
            "customer_email": "VARCHAR(255)",
            "customer_phone": "VARCHAR(40)",
            "delivery_service": "VARCHAR(32)",
            "delivery_city": "VARCHAR(160)",
            "delivery_branch": "VARCHAR(160)",
            "delivery_postal_code": "VARCHAR(20)",
            "delivery_address": "VARCHAR(300)",
            "comment": "TEXT",
            "tracking_number": "VARCHAR(120)",
            "mono_invoice_id": "VARCHAR(120)",
            "payment_event_at": "DATETIME",
            "created_at": "DATETIME",
            "updated_at": "DATETIME",
        },
        "store_settings": {
            "online_payment_enabled": "BOOLEAN DEFAULT 1",
            "bank_transfer_enabled": "BOOLEAN DEFAULT 1",
            "contact_phone": "VARCHAR(60)",
            "contact_email": "VARCHAR(255)",
            "contact_address": "VARCHAR(300)",
            "contact_telegram": "VARCHAR(160)",
            "shipping_notice": "VARCHAR(240) DEFAULT 'Відправка замовлень відбувається протягом 1–3 робочих днів.'",
        },
    }

    with engine.begin() as conn:
        for table_name, columns in additions.items():
            if table_name not in existing_tables:
                continue
            current = {c["name"] for c in inspect(engine).get_columns(table_name)}
            for column_name, column_type in columns.items():
                if column_name in current:
                    continue
                sql_type = _type_sql(dialect, column_type)
                conn.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {sql_type}'))

        # Some early TopBearing builds used product_images.image_url instead of url.
        # Copy it once after adding the new canonical column, without deleting legacy data.
        if "product_images" in existing_tables:
            image_columns = {c["name"] for c in inspect(engine).get_columns("product_images")}
            if "url" in image_columns and "image_url" in image_columns:
                conn.execute(text('UPDATE "product_images" SET "url" = "image_url" WHERE "url" IS NULL AND "image_url" IS NOT NULL'))
