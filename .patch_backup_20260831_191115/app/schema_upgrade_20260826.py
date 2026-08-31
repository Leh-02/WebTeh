from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


_COLUMNS = {
    "brands": {
        "country": "VARCHAR(120)",
    },
    "products": {
        "alternative_markings": "TEXT",
        "manufacturing_country": "VARCHAR(120)",
    },
    "orders": {
        "payment_provider": "VARCHAR(32)",
        "paid_at": "TIMESTAMP",
        "refunded_at": "TIMESTAMP",
    },
}


def ensure_schema_20260826(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table_name, columns in _COLUMNS.items():
            if table_name not in existing_tables:
                continue

            current = {item["name"] for item in inspector.get_columns(table_name)}
            for column_name, sql_type in columns.items():
                if column_name in current:
                    continue
                conn.execute(
                    text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {sql_type}')
                )
                current.add(column_name)
