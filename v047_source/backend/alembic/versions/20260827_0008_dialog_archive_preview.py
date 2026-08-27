"""VK Search v0.4.9 dialog archive and preview fields.

Revision ID: 20260827_0008
Revises: 20260827_0007
"""
from alembic import op
import sqlalchemy as sa

revision = "20260827_0008"
down_revision = "20260827_0007"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {str(row["name"]) for row in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {str(row["name"]) for row in sa.inspect(op.get_bind()).get_indexes(table) if row.get("name")}


def upgrade() -> None:
    columns = _columns("dialogs")
    with op.batch_alter_table("dialogs") as batch:
        if "is_archived" not in columns:
            batch.add_column(sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("0")))
        if "archived_at" not in columns:
            batch.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))
        if "notifications_muted_by_app" not in columns:
            batch.add_column(sa.Column("notifications_muted_by_app", sa.Boolean(), nullable=False, server_default=sa.text("0")))
        if "last_message_vk_id" not in columns:
            batch.add_column(sa.Column("last_message_vk_id", sa.Integer(), nullable=True))
        if "last_message_preview" not in columns:
            batch.add_column(sa.Column("last_message_preview", sa.Text(), nullable=False, server_default=""))
        if "last_message_outgoing" not in columns:
            batch.add_column(sa.Column("last_message_outgoing", sa.Boolean(), nullable=False, server_default=sa.text("0")))
        if "last_message_deleted" not in columns:
            batch.add_column(sa.Column("last_message_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")))

    indexes = _indexes("dialogs")
    if "ix_dialogs_is_archived" not in indexes:
        op.create_index("ix_dialogs_is_archived", "dialogs", ["is_archived"], unique=False)
    if "ix_dialogs_last_message_vk_id" not in indexes:
        op.create_index("ix_dialogs_last_message_vk_id", "dialogs", ["last_message_vk_id"], unique=False)


def downgrade() -> None:
    indexes = _indexes("dialogs")
    if "ix_dialogs_last_message_vk_id" in indexes:
        op.drop_index("ix_dialogs_last_message_vk_id", table_name="dialogs")
    if "ix_dialogs_is_archived" in indexes:
        op.drop_index("ix_dialogs_is_archived", table_name="dialogs")

    columns = _columns("dialogs")
    with op.batch_alter_table("dialogs") as batch:
        for name in (
            "last_message_deleted",
            "last_message_outgoing",
            "last_message_preview",
            "last_message_vk_id",
            "notifications_muted_by_app",
            "archived_at",
            "is_archived",
        ):
            if name in columns:
                batch.drop_column(name)
