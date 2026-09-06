"""Add Viber contact to store settings.

Revision ID: 20260902_01
Revises: 20260830_01
"""
from alembic import op
import sqlalchemy as sa

revision = "20260902_01"
down_revision = "20260830_01"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return column in {item["name"] for item in inspector.get_columns(table)}


def upgrade():
    bind = op.get_bind()
    if not _has_column(bind, "store_settings", "contact_viber"):
        op.add_column("store_settings", sa.Column("contact_viber", sa.String(length=160), nullable=True))


def downgrade():
    bind = op.get_bind()
    if _has_column(bind, "store_settings", "contact_viber"):
        op.drop_column("store_settings", "contact_viber")
