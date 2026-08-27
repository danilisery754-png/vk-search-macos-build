"""VK Search v0.4.7 account-scoped dialog folders.

Revision ID: 20260827_0006
Revises: 20260827_0005
"""
from alembic import op
import sqlalchemy as sa

revision = "20260827_0006"
down_revision = "20260827_0005"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "dialog_folders" not in tables:
        op.create_table(
            "dialog_folders",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("account_id", "name", name="dialog_folder_name_per_account"),
        )
        op.create_index("ix_dialog_folders_account_id", "dialog_folders", ["account_id"], unique=False)
    if "dialog_folder_members" not in tables:
        op.create_table(
            "dialog_folder_members",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("folder_id", sa.Integer(), nullable=False),
            sa.Column("dialog_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["folder_id"], ["dialog_folders.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["dialog_id"], ["dialogs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("folder_id", "dialog_id", name="dialog_once_per_folder"),
        )
        op.create_index("ix_dialog_folder_members_folder_id", "dialog_folder_members", ["folder_id"], unique=False)
        op.create_index("ix_dialog_folder_members_dialog_id", "dialog_folder_members", ["dialog_id"], unique=False)


def downgrade() -> None:
    tables = _tables()
    if "dialog_folder_members" in tables:
        op.drop_table("dialog_folder_members")
    if "dialog_folders" in tables:
        op.drop_table("dialog_folders")
