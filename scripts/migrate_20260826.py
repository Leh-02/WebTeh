from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import engine
from app.schema_upgrade_20260826 import ensure_schema_20260826


def main() -> None:
    ensure_schema_20260826(engine)
    print("TopBearing schema 2026-08-26: OK")


if __name__ == "__main__":
    main()
