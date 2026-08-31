"""Long-running worker that releases expired online-payment stock reservations."""
import os
import time
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.database import SessionLocal
from app.services.stock_service import release_expired_reservations

INTERVAL = max(60, int(os.getenv("STOCK_CLEANUP_INTERVAL_SECONDS", "300")))
while True:
    try:
        with SessionLocal() as db:
            count = release_expired_reservations(db, limit=500)
            db.commit()
            if count:
                print(f"Released {count} expired reservation(s).", flush=True)
    except Exception as exc:
        print(f"Stock reservation cleanup failed: {exc}", flush=True)
    time.sleep(INTERVAL)
