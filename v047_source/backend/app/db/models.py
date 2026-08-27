from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AttemptState, FinalOutcome, WorkItemState
from app.db.base import Base


def enum_values(enum_class):
    return [item.value for item in enum_class]


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class Account(Base, TimestampMixin):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    vk_user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(120), default="")
    last_name: Mapped[str] = mapped_column(String(120), default="")
    profile_url: Mapped[str] = mapped_column(String(500), default="")
    avatar_url: Mapped[str] = mapped_column(String(1000), default="")
    note: Mapped[str] = mapped_column(String(250), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    auth_status: Mapped[str] = mapped_column(String(40), default="requires_login")
    work_status: Mapped[str] = mapped_column(String(40), default="stopped")
    health_status: Mapped[str] = mapped_column(
        String(40), default="unknown", nullable=False, server_default=text("'unknown'")
    )
    health_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    health_detail: Mapped[str] = mapped_column(
        Text, default="", nullable=False, server_default=text("''")
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    unread_count: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def display_name(self) -> str:
        return self.note.strip() or f"{self.first_name} {self.last_name}".strip() or f"Аккаунт {self.vk_user_id}"


class AccountQuota(Base, TimestampMixin):
    __tablename__ = "account_quotas"

    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    window_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    window_ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    consumed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    account: Mapped[Account] = relationship()


class AccountSecret(Base, TimestampMixin):
    __tablename__ = "account_secrets"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), unique=True)
    encrypted_token: Mapped[bytes] = mapped_column(LargeBinary)
    token_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    browser_profile: Mapped[str] = mapped_column(String(1000))
    account: Mapped[Account] = relationship()


class Setting(Base, TimestampMixin):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text)


class QuickReply(Base, TimestampMixin):
    __tablename__ = "quick_replies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)


class Community(Base, TimestampMixin):
    __tablename__ = "communities"

    id: Mapped[int] = mapped_column(primary_key=True)
    vk_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    screen_name: Mapped[str] = mapped_column(String(250), default="")
    name: Mapped[str] = mapped_column(String(500), default="")
    canonical_url: Mapped[str] = mapped_column(String(500), index=True)
    avatar_url: Mapped[str] = mapped_column(String(1000), default="")


class Run(Base, TimestampMixin):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    state: Mapped[str] = mapped_column(String(40), default="created", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    original_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class WorkItem(Base, TimestampMixin):
    __tablename__ = "work_items"
    __table_args__ = (
        UniqueConstraint("run_id", "community_id", name="work_item_once_per_run"),
        Index("ix_work_claim", "assigned_account_id", "state", "next_retry_at"),
        Index("ix_work_lease", "state", "lease_expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id", ondelete="RESTRICT"), index=True)
    assigned_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    account_note_snapshot: Mapped[str] = mapped_column(String(250), default="")
    original_input: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[WorkItemState] = mapped_column(
        Enum(WorkItemState, values_callable=enum_values, native_enum=False),
        default=WorkItemState.WAITING,
        index=True,
    )
    attempts_count: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    quota_counted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")

    account: Mapped[Account | None] = relationship()
    community: Mapped[Community] = relationship()
    run: Mapped[Run] = relationship()


class SendAttempt(Base, TimestampMixin):
    __tablename__ = "send_attempts"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="send_attempt_idempotency"),
        Index("ix_attempt_work_direction", "work_item_id", "direction"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    work_item_id: Mapped[int] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"))
    direction: Mapped[str] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    random_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[AttemptState] = mapped_column(
        Enum(AttemptState, values_callable=enum_values, native_enum=False),
        default=AttemptState.NOT_ATTEMPTED,
    )
    vk_object_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_class: Mapped[str] = mapped_column(String(60), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    diagnostic_json: Mapped[str] = mapped_column(Text, default="{}")


class Result(Base, TimestampMixin):
    __tablename__ = "results"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_item_id: Mapped[int] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"), unique=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    message_state: Mapped[AttemptState] = mapped_column(
        Enum(AttemptState, values_callable=enum_values, native_enum=False), default=AttemptState.NOT_ATTEMPTED
    )
    message_reason: Mapped[str] = mapped_column(Text, default="")
    suggested_state: Mapped[AttemptState] = mapped_column(
        Enum(AttemptState, values_callable=enum_values, native_enum=False), default=AttemptState.NOT_ATTEMPTED
    )
    suggested_reason: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[FinalOutcome] = mapped_column(
        Enum(FinalOutcome, values_callable=enum_values, native_enum=False), default=FinalOutcome.PENDING, index=True
    )
    destination: Mapped[str] = mapped_column(String(80), default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Dialog(Base, TimestampMixin):
    __tablename__ = "dialogs"
    __table_args__ = (UniqueConstraint("account_id", "peer_id", name="dialog_per_account"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    peer_id: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500), default="")
    avatar_url: Mapped[str] = mapped_column(String(1000), default="")
    unread_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    can_write: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    write_disabled_reason: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_archived: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True, server_default=text("0")
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notifications_muted_by_app: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("0")
    )
    last_message_vk_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    last_message_preview: Mapped[str] = mapped_column(
        Text, default="", nullable=False, server_default=text("''")
    )
    last_message_outgoing: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("0")
    )
    last_message_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("0")
    )


class DialogFolder(Base, TimestampMixin):
    __tablename__ = "dialog_folders"
    __table_args__ = (UniqueConstraint("account_id", "name", name="dialog_folder_name_per_account"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class DialogFolderMember(Base, TimestampMixin):
    __tablename__ = "dialog_folder_members"
    __table_args__ = (UniqueConstraint("folder_id", "dialog_id", name="dialog_once_per_folder"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    folder_id: Mapped[int] = mapped_column(ForeignKey("dialog_folders.id", ondelete="CASCADE"), index=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey("dialogs.id", ondelete="CASCADE"), index=True)


class Message(Base, TimestampMixin):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("account_id", "vk_message_id", name="message_per_account"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey("dialogs.id", ondelete="CASCADE"), index=True)
    vk_message_id: Mapped[int] = mapped_column(Integer)
    from_id: Mapped[int] = mapped_column(Integer)
    outgoing: Mapped[bool] = mapped_column(Boolean, default=False)
    body: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime] = mapped_column(DateTime)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    attachments_json: Mapped[str] = mapped_column(Text, default="[]")
    conversation_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    updated_at_vk: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reply_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    forwards_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    reactions_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    raw_meta_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(20), default="info", index=True)
    category: Mapped[str] = mapped_column(String(30), default="system", nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(60), default="", nullable=False, index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    work_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True
    )
    user_message: Mapped[str] = mapped_column(Text)
    technical_json: Mapped[str] = mapped_column(Text, default="{}")
