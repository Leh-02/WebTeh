"""Dynamic catalogue hierarchy and richer product specifications.

Revision ID: 20260922_01
Revises: 20260902_01
"""
from alembic import op
import sqlalchemy as sa

revision = "20260922_01"
down_revision = "20260902_01"
branch_labels = None
depends_on = None


def _tables(bind):
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table):
    if table not in _tables(bind):
        return set()
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _indexes(bind, table):
    if table not in _tables(bind):
        return set()
    return {i["name"] for i in sa.inspect(bind).get_indexes(table)}


def _foreign_keys(bind, table):
    if table not in _tables(bind):
        return []
    return sa.inspect(bind).get_foreign_keys(table)


def _fks(bind, table):
    return {fk.get("name") for fk in _foreign_keys(bind, table)}


def _has_parent_fk(bind):
    for fk in _foreign_keys(bind, "categories"):
        if fk.get("referred_table") == "categories" and fk.get("constrained_columns") == ["parent_id"]:
            return True
    return False


def _add(bind, table, column):
    if table in _tables(bind) and column.name not in _columns(bind, table):
        op.add_column(table, column)


def _ensure_category(bind, code, name, product_type, sort_order, parent_code=None, description=None):
    categories = sa.table(
        "categories",
        sa.column("id", sa.Integer),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("parent_id", sa.Integer),
        sa.column("product_type", sa.String),
        sa.column("show_in_menu", sa.Boolean),
        sa.column("is_active", sa.Boolean),
        sa.column("sort_order", sa.Integer),
        sa.column("require_prepayment", sa.Boolean),
        sa.column("cod_allowed", sa.Boolean),
    )
    existing = bind.execute(sa.select(categories.c.id).where(categories.c.code == code)).scalar_one_or_none()
    parent_id = None
    if parent_code:
        parent_id = bind.execute(sa.select(categories.c.id).where(categories.c.code == parent_code)).scalar_one_or_none()
    values = {
        "name": name,
        "description": description,
        "parent_id": parent_id,
        "product_type": product_type,
        "show_in_menu": True,
        "is_active": True,
        "sort_order": sort_order,
        "require_prepayment": False,
        "cod_allowed": True,
    }
    if existing is None:
        bind.execute(categories.insert().values(code=code, **values))
    else:
        # Preserve a custom description if one already exists; everything else
        # is safe to normalize for the first hierarchy migration.
        current_description = bind.execute(
            sa.select(categories.c.description).where(categories.c.id == existing)
        ).scalar_one_or_none()
        if current_description:
            values.pop("description")
        bind.execute(categories.update().where(categories.c.id == existing).values(**values))


def upgrade():
    bind = op.get_bind()

    _add(bind, "categories", sa.Column("parent_id", sa.Integer(), nullable=True))
    _add(bind, "categories", sa.Column("product_type", sa.String(length=32), nullable=False, server_default="generic"))
    _add(bind, "categories", sa.Column("show_in_menu", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    if "categories" in _tables(bind):
        if "ix_categories_parent_id" not in _indexes(bind, "categories"):
            op.create_index("ix_categories_parent_id", "categories", ["parent_id"], unique=False)
        if "ix_categories_product_type" not in _indexes(bind, "categories"):
            op.create_index("ix_categories_product_type", "categories", ["product_type"], unique=False)
        if not _has_parent_fk(bind):
            try:
                op.create_foreign_key(
                    "fk_categories_parent_id",
                    "categories",
                    "categories",
                    ["parent_id"],
                    ["id"],
                    ondelete="RESTRICT",
                )
            except NotImplementedError:
                # SQLite development DBs cannot ALTER TABLE to add a FK. The
                # ORM relationship still works; production PostgreSQL gets it.
                pass

        op.execute(sa.text("""
            UPDATE categories SET product_type = CASE
                WHEN lower(code) IN ('bearing','bearings') THEN 'bearings'
                WHEN lower(code) IN ('belt','belts') THEN 'belts'
                WHEN lower(code) IN ('seal','seals') THEN 'seals'
                WHEN lower(code) IN ('lubricant','lubricants') THEN 'lubricants'
                WHEN lower(code) IN ('accessory','accessories') THEN 'accessories'
                ELSE COALESCE(NULLIF(product_type,''), 'generic')
            END
        """))

    _add(bind, "products", sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    for column in [
        sa.Column("rolling_element", sa.String(length=40), nullable=True),
        sa.Column("construction", sa.String(length=100), nullable=True),
        sa.Column("series_type", sa.String(length=80), nullable=True),
    ]:
        _add(bind, "bearing_specs", column)
    if "bearing_specs" in _tables(bind):
        for name, column in [
            ("ix_bearing_specs_rolling_element", "rolling_element"),
            ("ix_bearing_specs_construction", "construction"),
            ("ix_bearing_specs_series_type", "series_type"),
        ]:
            if name not in _indexes(bind, "bearing_specs"):
                op.create_index(name, "bearing_specs", [column], unique=False)

    _add(bind, "belt_specs", sa.Column("ribs", sa.Integer(), nullable=True))

    # Main customer-facing roots.
    _ensure_category(bind, "bearings", "Підшипники", "bearings", 10, description="Підшипники за конструкцією та розмірами")
    _ensure_category(bind, "belts", "Пасові ремені", "belts", 20, description="Приводні ремені за типом, профілем і довжиною")
    _ensure_category(bind, "seals", "Сальники та манжети", "seals", 30, description="Сальники та манжети за розмірами")

    # Bearing subcategories. These are deliberately broad; row count, rolling
    # element and NU/NJ/NUP series remain structured product characteristics.
    bearing_children = [
        ("bearing-radial-ball", "Кулькові радіальні", 110),
        ("bearing-self-aligning-ball", "Самовстановлювальні кулькові", 120),
        ("bearing-angular-contact", "Радіально-упорні кулькові", 130),
        ("bearing-thrust-ball", "Упорні кулькові", 140),
        ("bearing-roller", "Роликові", 150),
        ("bearing-spherical-roller", "Сферичні роликові", 160),
        ("bearing-cylindrical-roller", "Циліндричні роликові", 170),
        ("bearing-tapered-roller", "Конічні роликові", 180),
        ("bearing-needle", "Голчасті", 190),
        ("bearing-thrust-roller", "Упорні роликові", 200),
        ("bearing-housed", "Корпусні підшипники та вузли", 210),
    ]
    for code, name, order in bearing_children:
        _ensure_category(bind, code, name, "bearings", order, parent_code="bearings")

    belt_children = [
        ("belt-v", "Клинові", 310),
        ("belt-timing", "Зубчасті", 320),
        ("belt-poly-v", "Поліклинові", 330),
        ("belt-multi-groove", "Багаторучейні", 340),
    ]
    for code, name, order in belt_children:
        _ensure_category(bind, code, name, "belts", order, parent_code="belts")

    # The user explicitly wants seals/manchettes to remain one category, so no
    # child categories are seeded under ``seals``.


def downgrade():
    bind = op.get_bind()
    # Data categories are intentionally not deleted on downgrade because they
    # may already contain products created by the administrator.
    if "belt_specs" in _tables(bind) and "ribs" in _columns(bind, "belt_specs"):
        op.drop_column("belt_specs", "ribs")

    if "bearing_specs" in _tables(bind):
        for name in [
            "ix_bearing_specs_series_type",
            "ix_bearing_specs_construction",
            "ix_bearing_specs_rolling_element",
        ]:
            if name in _indexes(bind, "bearing_specs"):
                op.drop_index(name, table_name="bearing_specs")
        for column in ["series_type", "construction", "rolling_element"]:
            if column in _columns(bind, "bearing_specs"):
                op.drop_column("bearing_specs", column)

    if "products" in _tables(bind) and "is_featured" in _columns(bind, "products"):
        op.drop_column("products", "is_featured")

    if "categories" in _tables(bind):
        if "fk_categories_parent_id" in _fks(bind, "categories"):
            op.drop_constraint("fk_categories_parent_id", "categories", type_="foreignkey")
        for name in ["ix_categories_product_type", "ix_categories_parent_id"]:
            if name in _indexes(bind, "categories"):
                op.drop_index(name, table_name="categories")
        for column in ["show_in_menu", "product_type", "parent_id"]:
            if column in _columns(bind, "categories"):
                op.drop_column("categories", column)
