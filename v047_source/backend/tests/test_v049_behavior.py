from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.enums import AttemptState
from app.db.base import Base
from app.db.models import Account, Dialog
from app.services.accounts_v049 import AccountService
from app.services.dashboard import DashboardService
from app.services.inbox_v049_runtime import InboxService
from app.vk.client import VkActionResult


def make_engine(tmp_path, name: str):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / name}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return engine


def make_service(tmp_path, engine, runner=None):
    profiles = tmp_path / "profiles"
    profiles.mkdir(exist_ok=True)
    accounts = AccountService(engine, profiles, tmp_path / "secret.key")
    if runner is not None:
        accounts.run_vk = runner  # type: ignore[method-assign]
    return InboxService(engine, accounts)


def seed_account_dialog(engine, *, unread: int = 0, archived: bool = False):
    with Session(engine) as session:
        account = Account(vk_user_id=101, first_name="Иван", enabled=True, auth_status="ok")
        session.add(account)
        session.flush()
        dialog = Dialog(
            account_id=account.id,
            peer_id=202,
            title="Собеседник",
            unread_count=unread,
            is_archived=archived,
        )
        session.add(dialog)
        session.commit()
        return account.id, dialog.id


def test_dialog_v049_fields_have_safe_defaults(tmp_path):
    engine = make_engine(tmp_path, "fields.sqlite3")
    _account_id, dialog_id = seed_account_dialog(engine)
    with Session(engine) as session:
        row = session.get(Dialog, dialog_id)
        assert row is not None
        assert row.is_archived is False
        assert row.archived_at is None
        assert row.notifications_muted_by_app is False
        assert row.last_message_vk_id is None
        assert row.last_message_preview == ""
        assert row.last_message_outgoing is False
        assert row.last_message_deleted is False


@pytest.mark.parametrize(
    ("attachments", "expected"),
    [
        ([{"type": "photo", "photo": {}}], "Фото"),
        ([{"type": "video", "video": {}}], "Видео"),
        ([{"type": "doc", "doc": {"ext": "pdf"}}], "Документ"),
        ([{"type": "audio_message", "audio_message": {}}], "Голосовое сообщение"),
        ([{"type": "doc", "doc": {"ext": "ogg", "preview": {"audio_msg": {}}}}], "Голосовое сообщение"),
        ([{"type": "wall", "wall": {}}], "Вложение"),
    ],
)
def test_preview_attachment_labels(attachments, expected):
    _vk_id, preview, outgoing, deleted = InboxService._preview_from_raw(
        {"id": 9, "out": 0, "text": "", "attachments": attachments}
    )
    assert preview == expected
    assert outgoing is False
    assert deleted is False


def test_preview_normalizes_text_and_outgoing():
    vk_id, preview, outgoing, deleted = InboxService._preview_from_raw(
        {"id": 77, "out": 1, "text": "  привет\n\n   мир  ", "attachments": []}
    )
    assert vk_id == 77
    assert preview == "привет мир"
    assert outgoing is True
    assert deleted is False


def test_deleted_incoming_preserves_known_text_but_outgoing_does_not():
    incoming = InboxService._preview_from_raw(
        {"id": 10, "out": 0, "deleted": 1, "text": ""},
        previous_text="старый текст",
        previous_vk_id=10,
    )
    outgoing = InboxService._preview_from_raw(
        {"id": 10, "out": 1, "deleted": 1, "text": ""},
        previous_text="секретный старый текст",
        previous_vk_id=10,
    )
    assert incoming == (10, "старый текст", False, True)
    assert outgoing == (10, "", True, True)


async def test_sync_account_uses_conversation_last_message_without_per_dialog_history(tmp_path):
    engine = make_engine(tmp_path, "sync-preview.sqlite3")
    account_id, _dialog_id = seed_account_dialog(engine)
    calls: list[str] = []

    class Client:
        async def get_conversations(self, *, unread_only=False):
            calls.append("get_conversations")
            return {
                "profiles": [{"id": 202, "first_name": "Пётр", "last_name": "Петров"}],
                "groups": [],
                "items": [
                    {
                        "conversation": {"peer": {"id": 202}, "unread_count": 4, "can_write": {"allowed": True}},
                        "last_message": {"id": 555, "date": 1_700_000_000, "out": 1, "text": " последнее сообщение ", "attachments": []},
                    }
                ],
            }

        async def get_history(self, *args, **kwargs):
            calls.append("get_history")
            raise AssertionError("sync_account must not fetch history per dialog")

    async def runner(_account_id, operation, **_kwargs):
        return await operation(Client()), None

    service = make_service(tmp_path, engine, runner)
    result = await service.sync_account(account_id)
    assert result["ok"] is True
    assert calls == ["get_conversations"]
    with Session(engine) as session:
        row = session.scalar(select(Dialog).where(Dialog.account_id == account_id))
        assert row is not None
        assert row.last_message_vk_id == 555
        assert row.last_message_preview == "последнее сообщение"
        assert row.last_message_outgoing is True


async def test_archive_local_fallback_never_blocks_archiving_and_restore_is_explicit(tmp_path):
    engine = make_engine(tmp_path, "archive.sqlite3")
    _account_id, dialog_id = seed_account_dialog(engine, unread=3)

    async def runner(_account_id, operation, **_kwargs):
        class Client:
            async def set_peer_notifications(self, peer_id: int, enabled: bool):
                return VkActionResult(AttemptState.FAILED_FINAL, reason="unsupported")
        return await operation(Client())

    service = make_service(tmp_path, engine, runner)
    archived = await service.archive_dialog(dialog_id)
    assert archived["ok"] is True
    assert archived["notifications_changed"] is False
    assert service.list_dialogs() == []
    archived_rows = service.list_dialogs(archived=True)
    assert [row["id"] for row in archived_rows] == [dialog_id]
    assert archived_rows[0]["is_archived"] is True
    assert DashboardService(engine).snapshot()["metrics"]["unread"] == 0

    restored = await service.restore_dialog(dialog_id)
    assert restored["ok"] is True
    assert [row["id"] for row in service.list_dialogs()] == [dialog_id]


async def test_archive_notification_state_only_unmutes_when_app_proved_it_changed_state(tmp_path):
    engine = make_engine(tmp_path, "archive-mute.sqlite3")
    _account_id, dialog_id = seed_account_dialog(engine)
    calls: list[tuple[int, bool]] = []

    async def runner(_account_id, operation, **_kwargs):
        class Client:
            async def set_peer_notifications(self, peer_id: int, enabled: bool):
                calls.append((peer_id, enabled))
                if enabled:
                    return VkActionResult(AttemptState.SENT, raw={"changed": True})
                return VkActionResult(
                    AttemptState.SENT,
                    raw={"changed": True, "previous_enabled": True},
                )
        return await operation(Client())

    service = make_service(tmp_path, engine, runner)
    archived = await service.archive_dialog(dialog_id)
    assert archived["notifications_changed"] is True
    with Session(engine) as session:
        assert session.get(Dialog, dialog_id).notifications_muted_by_app is True
    restored = await service.restore_dialog(dialog_id)
    assert restored["notifications_changed"] is True
    assert calls == [(202, False), (202, True)]
    with Session(engine) as session:
        assert session.get(Dialog, dialog_id).notifications_muted_by_app is False


async def test_archive_does_not_claim_previously_muted_notifications_or_unmute_them(tmp_path):
    engine = make_engine(tmp_path, "archive-already-muted.sqlite3")
    _account_id, dialog_id = seed_account_dialog(engine)
    calls: list[tuple[int, bool]] = []

    async def runner(_account_id, operation, **_kwargs):
        class Client:
            async def set_peer_notifications(self, peer_id: int, enabled: bool):
                calls.append((peer_id, enabled))
                return VkActionResult(
                    AttemptState.SENT,
                    raw={"changed": False, "previous_enabled": False},
                )
        return await operation(Client())

    service = make_service(tmp_path, engine, runner)
    archived = await service.archive_dialog(dialog_id)
    assert archived["ok"] is True
    assert archived["notifications_changed"] is False
    with Session(engine) as session:
        assert session.get(Dialog, dialog_id).notifications_muted_by_app is False

    restored = await service.restore_dialog(dialog_id)
    assert restored["ok"] is True
    assert restored["notifications_changed"] is False
    assert calls == [(202, False)]


def test_archived_dialogs_do_not_count_toward_dashboard_unread(tmp_path):
    engine = make_engine(tmp_path, "unread.sqlite3")
    with Session(engine) as session:
        account = Account(vk_user_id=1, first_name="A", enabled=True, auth_status="ok")
        session.add(account)
        session.flush()
        session.add_all(
            [
                Dialog(account_id=account.id, peer_id=2, title="Обычный", unread_count=1, is_archived=False),
                Dialog(account_id=account.id, peer_id=3, title="Архив", unread_count=9, is_archived=True),
            ]
        )
        session.commit()
    assert DashboardService(engine).snapshot()["metrics"]["unread"] == 1
