"""VK Search v0.4.8 account health fields.

Revision ID: 20260827_0007
Revises: 20260827_0006
"""
from alembic import op
import sqlalchemy as sa

revision = "20260827_0007"
down_revision = "20260827_0006"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {str(row["name"]) for row in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    columns = _columns("accounts")
    with op.batch_alter_table("accounts") as batch:
        if "health_status" not in columns:
            batch.add_column(sa.Column("health_status", sa.String(length=40), nullable=False, server_default="unknown"))
        if "health_checked_at" not in columns:
            batch.add_column(sa.Column("health_checked_at", sa.DateTime(), nullable=True))
        if "health_detail" not in columns:
            batch.add_column(sa.Column("health_detail", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    columns = _columns("accounts")
    with op.batch_alter_table("accounts") as batch:
        if "health_detail" in columns:
            batch.drop_column("health_detail")
        if "health_checked_at" in columns:
            batch.drop_column("health_checked_at")
        if "health_status" in columns:
            batch.drop_column("health_status")
