"""v0.4.6 messenger metadata, quick replies, pins, structured logs.

Revision ID: 20260827_0005
Revises: 20260826_0004
"""
from alembic import op
import sqlalchemy as sa

revision = "20260827_0005"
down_revision = "20260826_0004"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    tables = _tables()
    if "quick_replies" not in tables:
        op.create_table(
            "quick_replies",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_quick_replies_position", "quick_replies", ["position"], unique=False)

    dialog_cols = _columns("dialogs")
    if "is_pinned" not in dialog_cols:
        op.add_column("dialogs", sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "pinned_at" not in dialog_cols:
        op.add_column("dialogs", sa.Column("pinned_at", sa.DateTime(), nullable=True))
    if "ix_dialogs_is_pinned" not in _indexes("dialogs"):
        op.create_index("ix_dialogs_is_pinned", "dialogs", ["is_pinned"], unique=False)

    msg_cols = _columns("messages")
    for name, column in (
        ("conversation_message_id", sa.Column("conversation_message_id", sa.Integer(), nullable=True)),
        ("updated_at_vk", sa.Column("updated_at_vk", sa.DateTime(), nullable=True)),
        ("deleted", sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("reply_json", sa.Column("reply_json", sa.Text(), nullable=False, server_default="{}")),
        ("forwards_json", sa.Column("forwards_json", sa.Text(), nullable=False, server_default="[]")),
        ("reactions_json", sa.Column("reactions_json", sa.Text(), nullable=False, server_default="[]")),
        ("raw_meta_json", sa.Column("raw_meta_json", sa.Text(), nullable=False, server_default="{}")),
    ):
        if name not in msg_cols:
            op.add_column("messages", column)
    if "ix_messages_conversation_message_id" not in _indexes("messages"):
        op.create_index("ix_messages_conversation_message_id", "messages", ["conversation_message_id"], unique=False)

    log_cols = _columns("event_logs")
    if "category" not in log_cols:
        op.add_column("event_logs", sa.Column("category", sa.String(length=30), nullable=False, server_default="system"))
    if "event_type" not in log_cols:
        op.add_column("event_logs", sa.Column("event_type", sa.String(length=60), nullable=False, server_default=""))
    if "ix_event_logs_category" not in _indexes("event_logs"):
        op.create_index("ix_event_logs_category", "event_logs", ["category"], unique=False)
    if "ix_event_logs_event_type" not in _indexes("event_logs"):
        op.create_index("ix_event_logs_event_type", "event_logs", ["event_type"], unique=False)


def downgrade() -> None:
    if "event_logs" in _tables():
        for index in ("ix_event_logs_event_type", "ix_event_logs_category"):
            if index in _indexes("event_logs"):
                op.drop_index(index, table_name="event_logs")
        for col in ("event_type", "category"):
            if col in _columns("event_logs"):
                op.drop_column("event_logs", col)
    if "messages" in _tables():
        if "ix_messages_conversation_message_id" in _indexes("messages"):
            op.drop_index("ix_messages_conversation_message_id", table_name="messages")
        for col in ("raw_meta_json", "reactions_json", "forwards_json", "reply_json", "deleted", "updated_at_vk", "conversation_message_id"):
            if col in _columns("messages"):
                op.drop_column("messages", col)
    if "dialogs" in _tables():
        if "ix_dialogs_is_pinned" in _indexes("dialogs"):
            op.drop_index("ix_dialogs_is_pinned", table_name="dialogs")
        for col in ("pinned_at", "is_pinned"):
            if col in _columns("dialogs"):
                op.drop_column("dialogs", col)
    if "quick_replies" in _tables():
        op.drop_table("quick_replies")
