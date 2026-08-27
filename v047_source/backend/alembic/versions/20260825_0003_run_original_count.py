"""Snapshot original run group count.

Revision ID: 20260825_0003
Revises: 20260825_0002
"""
from alembic import op
import sqlalchemy as sa

revision = "20260825_0003"
down_revision = "20260825_0002"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns("runs")}


def upgrade() -> None:
    if "original_count" not in _columns():
        op.add_column("runs", sa.Column("original_count", sa.Integer(), nullable=False, server_default="0"))
    op.execute(sa.text("""
        UPDATE runs
        SET original_count = (
            SELECT COUNT(*) FROM work_items WHERE work_items.run_id = runs.id
        )
        WHERE original_count = 0
    """))


def downgrade() -> None:
    if "original_count" in _columns():
        op.drop_column("runs", "original_count")
