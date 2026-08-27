"""Rolling daily account quota and durable waiting queue semantics.

Revision ID: 20260826_0004
Revises: 20260825_0003
"""
from alembic import op
import sqlalchemy as sa

revision = "20260826_0004"
down_revision = "20260825_0003"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    if "account_quotas" not in _table_names():
        op.create_table(
            "account_quotas",
            sa.Column("account_id", sa.Integer(), nullable=False),
            sa.Column("window_started_at", sa.DateTime(), nullable=True),
            sa.Column("window_ends_at", sa.DateTime(), nullable=True),
            sa.Column("consumed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("account_id"),
        )
        op.create_index("ix_account_quotas_window_ends_at", "account_quotas", ["window_ends_at"], unique=False)

    if "quota_counted_at" not in _columns("work_items"):
        op.add_column("work_items", sa.Column("quota_counted_at", sa.DateTime(), nullable=True))

    # v0.4.0's "limit_reached" meant only that one distribution pass was full.
    # In v0.4.1 the same logical run stays alive while rolling quota is exhausted.
    op.execute(sa.text("UPDATE runs SET state = 'waiting_limit' WHERE state = 'limit_reached'"))

    # Assigned-but-never-started rows came from the old upfront distributor.
    # Return them to the shared durable pool so v0.4.1 can claim them on demand.
    op.execute(sa.text("""
        UPDATE work_items
        SET state = 'waiting', assigned_account_id = NULL,
            account_note_snapshot = '', lease_owner = NULL,
            lease_expires_at = NULL
        WHERE state = 'assigned' AND started_at IS NULL
    """))


def downgrade() -> None:
    op.execute(sa.text("UPDATE runs SET state = 'limit_reached' WHERE state = 'waiting_limit'"))
    if "quota_counted_at" in _columns("work_items"):
        op.drop_column("work_items", "quota_counted_at")
    if "account_quotas" in _table_names():
        indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("account_quotas")}
        if "ix_account_quotas_window_ends_at" in indexes:
            op.drop_index("ix_account_quotas_window_ends_at", table_name="account_quotas")
        op.drop_table("account_quotas")
