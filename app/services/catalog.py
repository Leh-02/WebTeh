import re
from decimal import Decimal, InvalidOperation
from typing import Iterable

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
    "generic": "generic",
}

_DIM_RE = re.compile(
    r"(?P<a>\d+(?:[.,]\d+)?)\s*(?:x|х|×|\*|-|–|—)\s*"
    r"(?P<b>\d+(?:[.,]\d+)?)"
    r"(?:\s*(?:x|х|×|\*|-|–|—)\s*(?P<c>\d+(?:[.,]\d+)?))?",
    flags=re.IGNORECASE,
)

# Cyrillic letters that are commonly typed instead of visually identical Latin
# letters in industrial belt profiles (B/В, A/А, C/С, X/Х, etc.).
_PROFILE_TRANSLATION = str.maketrans(
    {
        "А": "A", "В": "B", "С": "C", "Е": "E", "К": "K", "М": "M",
        "Н": "H", "О": "O", "Р": "P", "Т": "T", "Х": "X",
        "а": "A", "в": "B", "с": "C", "е": "E", "к": "K", "м": "M",
        "н": "H", "о": "O", "р": "P", "т": "T", "х": "X",
    }
)


def normalize_category_code(code: str | None) -> str | None:
    if not code:
        return None
    return CATEGORY_ALIASES.get(code.strip().lower(), code.strip().lower())


def normalize_belt_profile(value: str | None) -> str | None:
    """Normalize user-entered belt profiles without changing their meaning.

    Examples: ``в`` -> ``B``, `` spz `` -> ``SPZ``, ``6 рк`` -> ``6PK``.
    Spaces and common separators are removed because catalogue profiles are
    identifiers rather than free text.
    """
    if not value:
        return None
    normalized = value.strip().translate(_PROFILE_TRANSLATION).upper()
    normalized = re.sub(r"[\s._-]+", "", normalized)
    return normalized or None


def _decimal(value: str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, AttributeError, ValueError):
        return None


def _integer(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
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
    category_ids: Iterable[int] | None = None,
    product_type: str | None = None,
    brand_id: int | None = None,
    sort: str = "relevance",
    subtype: str | None = None,
    profile: str | None = None,
    material: str | None = None,
    viscosity: str | None = None,
    rows: str | None = None,
    series_type: str | None = None,
    inner_min: str | None = None,
    inner_max: str | None = None,
    outer_min: str | None = None,
    outer_max: str | None = None,
    width_min: str | None = None,
    width_max: str | None = None,
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

    scoped_ids = [int(item) for item in (category_ids or [])]
    canonical_category = normalize_category_code(product_type or category_code)
    if scoped_ids:
        stmt = stmt.where(Product.category_id.in_(scoped_ids))
    elif category_code:
        normalized_code = normalize_category_code(category_code)
        aliases = [k for k, v in CATEGORY_ALIASES.items() if v == normalized_code]
        aliases.append(category_code.strip().lower())
        stmt = stmt.where(Product.category.has(Category.code.in_(sorted(set(aliases)))))

    if brand_id:
        stmt = stmt.where(Product.brand_id == brand_id)

    dims, keywords = parse_dimensions(q)
    if dims:
        if len(dims) == 3:
            a, b, c = dims
            conditions = []
            if canonical_category in {None, "bearings", "generic"}:
                spec = Product.bearing_spec.property.mapper.class_
                conditions.append(
                    Product.bearing_spec.has(
                        and_(
                            spec.inner_diameter_mm == a,
                            spec.outer_diameter_mm == b,
                            spec.width_mm == c,
                        )
                    )
                )
            if canonical_category in {None, "seals", "generic"}:
                spec = Product.seal_spec.property.mapper.class_
                conditions.append(
                    Product.seal_spec.has(
                        and_(
                            spec.inner_diameter_mm == a,
                            spec.outer_diameter_mm == b,
                            spec.width_mm == c,
                        )
                    )
                )
            if conditions:
                stmt = stmt.where(or_(*conditions))
        elif len(dims) == 2:
            a, b = dims
            conditions = []
            if canonical_category in {None, "bearings", "generic"}:
                spec = Product.bearing_spec.property.mapper.class_
                conditions.append(Product.bearing_spec.has(and_(spec.inner_diameter_mm == a, spec.outer_diameter_mm == b)))
            if canonical_category in {None, "seals", "generic"}:
                spec = Product.seal_spec.property.mapper.class_
                conditions.append(Product.seal_spec.has(and_(spec.inner_diameter_mm == a, spec.outer_diameter_mm == b)))
            if conditions:
                stmt = stmt.where(or_(*conditions))

    if keywords:
        for term in [t for t in re.split(r"\s+", keywords.strip()) if t]:
            pattern = f"%{term.lower()}%"
            normalized_profile = normalize_belt_profile(term)
            text_conditions = [
                func.lower(Product.name).like(pattern),
                func.lower(Product.sku).like(pattern),
                func.lower(func.coalesce(Product.manufacturer_code, "")).like(pattern),
                func.lower(func.coalesce(Product.alternative_markings, "")).like(pattern),
                Product.brand.has(func.lower(Brand.name).like(pattern)),
            ]
            if normalized_profile:
                belt = Product.belt_spec.property.mapper.class_
                text_conditions.append(
                    Product.belt_spec.has(func.upper(func.coalesce(belt.profile, "")) == normalized_profile)
                )
            stmt = stmt.where(or_(*text_conditions))

    # Technical filters. Relationship .has() keeps the main Product select free
    # of duplicate rows and works well for the current catalogue scale.
    if subtype and canonical_category in {None, "bearings", "generic"}:
        spec = Product.bearing_spec.property.mapper.class_
        stmt = stmt.where(Product.bearing_spec.has(func.lower(func.coalesce(spec.subtype, "")) == subtype.strip().lower()))
    if rows and canonical_category in {None, "bearings", "generic"}:
        rows_i = _integer(rows)
        if rows_i is not None:
            spec = Product.bearing_spec.property.mapper.class_
            stmt = stmt.where(Product.bearing_spec.has(spec.rows == rows_i))
    if series_type and canonical_category in {None, "bearings", "generic"}:
        spec = Product.bearing_spec.property.mapper.class_
        stmt = stmt.where(Product.bearing_spec.has(func.lower(func.coalesce(spec.series_type, "")) == series_type.strip().lower()))
    if profile and canonical_category in {None, "belts", "generic"}:
        normalized = normalize_belt_profile(profile)
        if normalized:
            spec = Product.belt_spec.property.mapper.class_
            stmt = stmt.where(Product.belt_spec.has(func.upper(func.coalesce(spec.profile, "")) == normalized))
    # Kept for backwards-compatible URLs/imports, even though material is no
    # longer exposed as a storefront seal filter.
    if material and canonical_category in {None, "seals", "generic"}:
        spec = Product.seal_spec.property.mapper.class_
        stmt = stmt.where(Product.seal_spec.has(func.lower(func.coalesce(spec.material, "")) == material.lower()))
    if viscosity and canonical_category in {None, "lubricants", "generic"}:
        spec = Product.lubricant_spec.property.mapper.class_
        stmt = stmt.where(Product.lubricant_spec.has(func.lower(func.coalesce(spec.viscosity, "")) == viscosity.lower()))

    inner_min_d, inner_max_d = _decimal(inner_min), _decimal(inner_max)
    outer_min_d, outer_max_d = _decimal(outer_min), _decimal(outer_max)
    width_min_d, width_max_d = _decimal(width_min), _decimal(width_max)
    length_min_d, length_max_d = _decimal(length_min), _decimal(length_max)

    def dimension_filter(field: str, minimum: Decimal | None, maximum: Decimal | None):
        nonlocal stmt
        if minimum is None and maximum is None:
            return
        conditions = []
        if canonical_category in {None, "bearings", "generic"}:
            rel = Product.bearing_spec
            spec = rel.property.mapper.class_
            parts = []
            if minimum is not None:
                parts.append(getattr(spec, field) >= minimum)
            if maximum is not None:
                parts.append(getattr(spec, field) <= maximum)
            conditions.append(rel.has(and_(*parts)))
        if canonical_category in {None, "seals", "generic"}:
            rel = Product.seal_spec
            spec = rel.property.mapper.class_
            parts = []
            if minimum is not None:
                parts.append(getattr(spec, field) >= minimum)
            if maximum is not None:
                parts.append(getattr(spec, field) <= maximum)
            conditions.append(rel.has(and_(*parts)))
        if conditions:
            stmt = stmt.where(or_(*conditions))

    dimension_filter("inner_diameter_mm", inner_min_d, inner_max_d)
    dimension_filter("outer_diameter_mm", outer_min_d, outer_max_d)
    dimension_filter("width_mm", width_min_d, width_max_d)

    if (length_min_d is not None or length_max_d is not None) and canonical_category in {None, "belts", "generic"}:
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
    elif sort == "name_asc":
        stmt = stmt.order_by(asc(Product.name), desc(Product.id))
    else:
        # Search relevance is intentionally simple for now; exact dimensions
        # and all search terms are already required above.
        stmt = stmt.order_by(desc(Product.is_featured), desc(Product.id))

    return stmt
