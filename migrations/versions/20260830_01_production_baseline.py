"""Production baseline for the pre-Alembic WebTeh database."""
from alembic import op
import sqlalchemy as sa

revision = "20260830_01"
down_revision = None
branch_labels = None
depends_on = None

def _tables(bind):
    return set(sa.inspect(bind).get_table_names())

def _columns(bind, table):
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}

def _add(bind, table, column):
    if table in _tables(bind) and column.name not in _columns(bind, table):
        op.add_column(table, column)

def upgrade():
    bind = op.get_bind()
    from app.database import Base
    import app.models  # noqa
    Base.metadata.create_all(bind=bind)

    for c in [
        sa.Column("full_name", sa.String(160), nullable=True),
        sa.Column("phone", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    ]: _add(bind, "users", c)

    for c in [
        sa.Column("name", sa.String(120), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("require_prepayment", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("cod_allowed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    ]: _add(bind, "categories", c)

    _add(bind, "brands", sa.Column("country", sa.String(120), nullable=True))

    for c in [
        sa.Column("online_payment_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("bank_transfer_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("contact_phone", sa.String(60), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("contact_address", sa.String(300), nullable=True),
        sa.Column("contact_telegram", sa.String(160), nullable=True),
        sa.Column("shipping_notice", sa.String(240), nullable=False, server_default="Відправка замовлень відбувається протягом 1–3 робочих днів."),
    ]: _add(bind, "store_settings", c)

    for c in [
        sa.Column("manufacturer_code", sa.String(120), nullable=True),
        sa.Column("alternative_markings", sa.Text(), nullable=True),
        sa.Column("manufacturing_country", sa.String(120), nullable=True),
        sa.Column("short_description", sa.String(500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("require_prepayment_override", sa.Boolean(), nullable=True),
        sa.Column("cod_allowed_override", sa.Boolean(), nullable=True),
        sa.Column("stock_qty", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("stock_is_tracked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("availability_status", sa.String(32), nullable=False, server_default="in_stock"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    ]: _add(bind, "products", c)

    for c in [
        sa.Column("url", sa.String(600), nullable=True),
        sa.Column("alt_text", sa.String(220), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    ]: _add(bind, "product_images", c)

    if "product_images" in _tables(bind):
        cols = _columns(bind, "product_images")
        if "image_url" in cols and "url" in cols:
            op.execute(sa.text("UPDATE product_images SET url=image_url WHERE (url IS NULL OR url='') AND image_url IS NOT NULL"))

    for c in [
        sa.Column("payment_status", sa.String(32), nullable=False, server_default="unpaid"),
        sa.Column("payment_method", sa.String(32), nullable=True),
        sa.Column("stock_restored", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("stock_state", sa.String(24), nullable=False, server_default="committed"),
        sa.Column("stock_reserved_until", sa.DateTime(), nullable=True),
        sa.Column("subtotal", sa.Numeric(12,2), nullable=False, server_default=sa.text("0")),
        sa.Column("delivery_price", sa.Numeric(12,2), nullable=False, server_default=sa.text("0")),
        sa.Column("customer_name", sa.String(160), nullable=True),
        sa.Column("customer_email", sa.String(255), nullable=True),
        sa.Column("customer_phone", sa.String(40), nullable=True),
        sa.Column("delivery_service", sa.String(32), nullable=True),
        sa.Column("delivery_city", sa.String(160), nullable=True),
        sa.Column("delivery_branch", sa.String(160), nullable=True),
        sa.Column("delivery_postal_code", sa.String(20), nullable=True),
        sa.Column("delivery_address", sa.String(300), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("tracking_number", sa.String(120), nullable=True),
        sa.Column("mono_invoice_id", sa.String(120), nullable=True),
        sa.Column("payment_provider", sa.String(32), nullable=True),
        sa.Column("payment_event_at", sa.DateTime(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("refunded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    ]: _add(bind, "orders", c)

    Base.metadata.create_all(bind=bind)

def downgrade():
    pass
