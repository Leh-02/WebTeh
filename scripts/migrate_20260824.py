"""Run the additive TopBearing 2026-08-24 schema migration explicitly.

The application also runs this compatibility migration on startup. This script is useful when
an administrator wants to migrate first and start the web process only after checking the DB.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base, engine
from app.schema_upgrade import ensure_schema_20260824


def main() -> None:
    ensure_schema_20260824(engine)
    Base.metadata.create_all(bind=engine)
    print("TopBearing schema update 2026-08-24 completed. Legacy payment-policy columns were preserved but are ignored.")


if __name__ == "__main__":
    main()
