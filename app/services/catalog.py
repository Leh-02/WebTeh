import re
from decimal import Decimal, InvalidOperation

from sqlalchemy import and_, asc, desc, func, or_, select
from sqlalchemy.orm import selectinload

from app.models import Brand, Category, Product

CATEGORY_ALIASES = {
    "bearing": "bearings",
    "bearings": "bearings",
    "belt": "belts",
    "belts": "belts",
    "seal": "seals",
    "seals": "seals",
    "lubricant": "lubricants",
    "lubricants": "lubricants",
    "accessory": "accessories",
    "accessories": "accessories",
}

_DIM_RE = re.compile(
    r"(?P<a>\d+(?:[.,]\d+)?)\s*(?:x|х|×|\*|-|–|—)\s*"
    r"(?P<b>\d+(?:[.,]\d+)?)"
    r"(?:\s*(?:x|х|×|\*|-|–|—)\s*(?P<c>\d+(?:[.,]\d+)?))?",
    flags=re.IGNORECASE,
)


def normalize_category_code(code: str | None) -> str | None:
    if not code:
        return None
    return CATEGORY_ALIASES.get(code.strip().lower(), code.strip().lower())


def _decimal(value: str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(value.replace(",", "."))
    except (InvalidOperation, AttributeError):
        return None


def parse_dimensions(query: str | None):
    if not query:
        return None, None
    match = _DIM_RE.search(query)
    if not match:
        return None, query.strip()
    values = [_decimal(match.group("a")), _decimal(match.group("b"))]
    if match.group("c") is not None:
        values.append(_decimal(match.group("c")))
    remainder = (query[: match.start()] + " " + query[match.end() :]).strip()
    remainder = re.sub(r"\s+", " ", remainder)
    return tuple(values), remainder


def build_catalog_statement(
    *,
    q: str | None = None,
    category_code: str | None = None,
    brand_id: int | None = None,
    sort: str = "relevance",
    subtype: str | None = None,
    profile: str | None = None,
    material: str | None = None,
    viscosity: str | None = None,
    inner_min: str | None = None,
    inner_max: str | None = None,
    outer_min: str | None = None,
    outer_max: str | None = None,
    length_min: str | None = None,
    length_max: str | None = None,
):
    stmt = (
        select(Product)
        .where(Product.is_active.is_(True))
        .options(
            selectinload(Product.category),
            selectinload(Product.brand),
            selectinload(Product.images),
            selectinload(Product.bearing_spec),
            selectinload(Product.belt_spec),
            selectinload(Product.seal_spec),
            selectinload(Product.lubricant_spec),
        )
    )

    canonical_category = normalize_category_code(category_code)
    if canonical_category:
        aliases = [k for k, v in CATEGORY_ALIASES.items() if v == canonical_category]
        stmt = stmt.where(Product.category.has(Category.code.in_(aliases)))

    if brand_id:
        stmt = stmt.where(Product.brand_id == brand_id)

    dims, keywords = parse_dimensions(q)
    if dims:
        if len(dims) == 3:
            a, b, c = dims
            stmt = stmt.where(
                or_(
                    Product.bearing_spec.has(
                        and_(
                            Product.bearing_spec.property.mapper.class_.inner_diameter_mm == a,
                            Product.bearing_spec.property.mapper.class_.outer_diameter_mm == b,
                            Product.bearing_spec.property.mapper.class_.width_mm == c,
                        )
                    ),
                    Product.seal_spec.has(
                        and_(
                            Product.seal_spec.property.mapper.class_.inner_diameter_mm == a,
                            Product.seal_spec.property.mapper.class_.outer_diameter_mm == b,
                            Product.seal_spec.property.mapper.class_.width_mm == c,
                        )
                    ),
                )
            )
        elif len(dims) == 2:
            a, b = dims
            stmt = stmt.where(
                or_(
                    Product.bearing_spec.has(
                        and_(
                            Product.bearing_spec.property.mapper.class_.inner_diameter_mm == a,
                            Product.bearing_spec.property.mapper.class_.outer_diameter_mm == b,
                        )
                    ),
                    Product.seal_spec.has(
                        and_(
                            Product.seal_spec.property.mapper.class_.inner_diameter_mm == a,
                            Product.seal_spec.property.mapper.class_.outer_diameter_mm == b,
                        )
                    ),
                )
            )

    if keywords:
        for term in [t for t in re.split(r"\s+", keywords.strip()) if t]:
            pattern = f"%{term.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Product.name).like(pattern),
                    func.lower(Product.sku).like(pattern),
                    func.lower(func.coalesce(Product.manufacturer_code, "")).like(pattern),
                    Product.brand.has(func.lower(Brand.name).like(pattern)),
                )
            )

    # Technical filters. Relationship .has() keeps the query simple and index-friendly enough for MVP scale.
    if subtype:
        spec = Product.bearing_spec.property.mapper.class_
        stmt = stmt.where(Product.bearing_spec.has(func.lower(func.coalesce(spec.subtype, "")) == subtype.lower()))
    if profile:
        spec = Product.belt_spec.property.mapper.class_
        stmt = stmt.where(Product.belt_spec.has(func.lower(func.coalesce(spec.profile, "")) == profile.lower()))
    if material:
        spec = Product.seal_spec.property.mapper.class_
        stmt = stmt.where(Product.seal_spec.has(func.lower(func.coalesce(spec.material, "")) == material.lower()))
    if viscosity:
        spec = Product.lubricant_spec.property.mapper.class_
        stmt = stmt.where(Product.lubricant_spec.has(func.lower(func.coalesce(spec.viscosity, "")) == viscosity.lower()))

    inner_min_d, inner_max_d = _decimal(inner_min), _decimal(inner_max)
    outer_min_d, outer_max_d = _decimal(outer_min), _decimal(outer_max)
    length_min_d, length_max_d = _decimal(length_min), _decimal(length_max)

    if inner_min_d is not None or inner_max_d is not None:
        conditions = []
        for rel in (Product.bearing_spec, Product.seal_spec):
            spec = rel.property.mapper.class_
            parts = []
            if inner_min_d is not None:
                parts.append(spec.inner_diameter_mm >= inner_min_d)
            if inner_max_d is not None:
                parts.append(spec.inner_diameter_mm <= inner_max_d)
            conditions.append(rel.has(and_(*parts)))
        stmt = stmt.where(or_(*conditions))

    if outer_min_d is not None or outer_max_d is not None:
        conditions = []
        for rel in (Product.bearing_spec, Product.seal_spec):
            spec = rel.property.mapper.class_
            parts = []
            if outer_min_d is not None:
                parts.append(spec.outer_diameter_mm >= outer_min_d)
            if outer_max_d is not None:
                parts.append(spec.outer_diameter_mm <= outer_max_d)
            conditions.append(rel.has(and_(*parts)))
        stmt = stmt.where(or_(*conditions))

    if length_min_d is not None or length_max_d is not None:
        spec = Product.belt_spec.property.mapper.class_
        parts = []
        if length_min_d is not None:
            parts.append(spec.length_mm >= length_min_d)
        if length_max_d is not None:
            parts.append(spec.length_mm <= length_max_d)
        stmt = stmt.where(Product.belt_spec.has(and_(*parts)))

    if sort == "price_asc":
        stmt = stmt.order_by(asc(Product.price), desc(Product.id))
    elif sort == "price_desc":
        stmt = stmt.order_by(desc(Product.price), desc(Product.id))
    elif sort == "newest":
        stmt = stmt.order_by(desc(Product.created_at), desc(Product.id))
    else:
        stmt = stmt.order_by(desc(Product.is_active), desc(Product.id))

    return stmt
