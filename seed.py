"""Seed canonical categories, store settings and optionally the first administrator.
Run after `alembic upgrade head`.
"""
import os
from decimal import Decimal
from sqlalchemy import func, select
from app.database import SessionLocal
from app.models import Brand, Category, StoreSettings, User
from app.security import hash_password

CATEGORIES = [
    ("bearings", "Підшипники", 10),
    ("belts", "Пасові ремені", 20),
    ("seals", "Сальники та манжети", 30),
    ("lubricants", "Змащення", 40),
    ("accessories", "Аксесуари", 50),
]

def main():
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    with SessionLocal() as db:
        for code, name, order in CATEGORIES:
            item = db.scalar(select(Category).where(Category.code == code))
            if not item:
                db.add(Category(code=code, name=name, is_active=True, sort_order=order))
            else:
                item.name = item.name or name
                item.is_active = True
                item.sort_order = order
        if not db.scalar(select(Brand).where(Brand.name == "Без бренду")):
            db.add(Brand(name="Без бренду", slug="bez-brendu"))
        if not db.get(StoreSettings, 1):
            db.add(StoreSettings(id=1, cod_enabled=True, cod_min_total=Decimal("500.00")))
        if email:
            admin = db.scalar(select(User).where(func.lower(User.email) == email))
            if admin:
                admin.role = "admin"; admin.is_active = True
            else:
                if len(password) < 12:
                    raise RuntimeError("ADMIN_PASSWORD must contain at least 12 characters")
                db.add(User(email=email, password_hash=hash_password(password), role="admin", is_active=True))
        db.commit()

if __name__ == "__main__":
    main()
