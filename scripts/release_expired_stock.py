from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.database import SessionLocal
from app.services.stock_service import release_expired_reservations

if __name__ == "__main__":
    with SessionLocal() as db:
        count = release_expired_reservations(db, limit=500)
        db.commit()
        print(f"Released {count} expired reservation(s).")
