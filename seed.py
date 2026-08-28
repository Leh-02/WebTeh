"""Seed canonical categories, store settings and the first administrator."""
import os
from decimal import Decimal

from sqlalchemy import func, select

from app.database import Base, SessionLocal, engine
from app.models import Brand, Category, StoreSettings, User
from app.schema_upgrade import ensure_schema_20260824
from app.security import hash_password

CATEGORIES = [
    ("bearings", "Підшипники", 10),
    ("belts", "Пасові ремені", 20),
    ("seals", "Сальники та манжети", 30),
    ("lubricants", "Змащення", 40),
    ("accessories", "Аксесуари", 50),
]


def main() -> None:
    ensure_schema_20260824(engine)
    Base.metadata.create_all(engine)
    email = os.getenv("ADMIN_EMAIL", "admin@topbearing.local").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "ChangeMe123!")

    with SessionLocal() as db:
        for code, name, order in CATEGORIES:
            category = db.scalar(select(Category).where(Category.code == code))
            if not category:
                db.add(Category(code=code, name=name, is_active=True, sort_order=order))
            else:
                category.name = category.name or name
                category.is_active = True
                category.sort_order = order

        if not db.scalar(select(Brand).where(Brand.name == "Без бренду")):
            db.add(Brand(name="Без бренду", slug="bez-brendu"))

        if not db.get(StoreSettings, 1):
            db.add(StoreSettings(id=1, cod_enabled=True, cod_min_total=Decimal("500.00")))

        admin = db.scalar(select(User).where(func.lower(User.email) == email))
        if admin:
            admin.role = "admin"
            admin.is_active = True
            # Deliberately do not silently reset an existing admin password.
            print(f"Admin already exists: {email}. Password was not changed.")
        else:
            db.add(User(email=email, password_hash=hash_password(password), role="admin", is_active=True))
            print(f"Created admin: {email}")
            print("Admin password comes from ADMIN_PASSWORD (development default is ChangeMe123!).")
        db.commit()


if __name__ == "__main__":
    main()
