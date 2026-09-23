from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Category, Product
from app.services.catalog import build_catalog_statement


def test_search_finds_product_by_alternative_marking():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        category = Category(code="bearings", name="Підшипники", is_active=True)
        db.add(category)
        db.flush()
        product = Product(
            sku="TB-BRG-TEST01",
            slug="6201-test",
            name="6201 2RS",
            manufacturer_code="6201 2RS",
            alternative_markings="180201\n6201-2RS",
            category_id=category.id,
            price=Decimal("100.00"),
            is_active=True,
        )
        db.add(product)
        db.commit()

        result = db.scalars(build_catalog_statement(q="180201")).all()
        assert [item.sku for item in result] == ["TB-BRG-TEST01"]


def test_bearing_only_filter_is_ignored_for_belts_category():
    sql = str(build_catalog_statement(category_code="belts", subtype="radial")).lower()
    assert "bearing_specs.subtype" not in sql


def test_belt_profile_normalizes_cyrillic_lookalikes():
    from app.services.catalog import normalize_belt_profile

    assert normalize_belt_profile(" в ") == "B"
    assert normalize_belt_profile("6 рк") == "6PK"
    assert normalize_belt_profile("spz-1000") == "SPZ1000"
