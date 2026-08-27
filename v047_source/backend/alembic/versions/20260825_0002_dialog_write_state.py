"""Persist dialog write availability.

Revision ID: 20260825_0002
Revises: 20260825_0001
"""
from alembic import op
import sqlalchemy as sa

revision = "20260825_0002"
down_revision = "20260825_0001"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns("dialogs")}


def upgrade() -> None:
    existing = _columns()
    if "can_write" not in existing:
        op.add_column("dialogs", sa.Column("can_write", sa.Boolean(), nullable=False, server_default=sa.true()))
    if "write_disabled_reason" not in existing:
        op.add_column(
            "dialogs",
            sa.Column("write_disabled_reason", sa.String(length=120), nullable=False, server_default=""),
        )


def downgrade() -> None:
    existing = _columns()
    if "write_disabled_reason" in existing:
        op.drop_column("dialogs", "write_disabled_reason")
    if "can_write" in existing:
        op.drop_column("dialogs", "can_write")
