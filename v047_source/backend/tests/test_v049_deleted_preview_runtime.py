from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.enums import AttemptState
from app.db.base import Base
from app.db.models import Account, Dialog, Message
from app.services.accounts_v049 import AccountService
from app.services.inbox_v049_runtime import InboxService
from app.vk.client import VkActionResult


def make_service(tmp_path, engine, runner=None):
    profiles = tmp_path / "profiles"
    profiles.mkdir(exist_ok=True)
    accounts = AccountService(engine, profiles, tmp_path / "secret.key")
    if runner is not None:
        accounts.run_vk = runner  # type: ignore[method-assign]
    return InboxService(engine, accounts)


def seed_last_message(engine, *, outgoing: bool, body: str, vk_id: int = 555):
    with Session(engine) as session:
        account = Account(vk_user_id=101, first_name="Иван", enabled=True, auth_status="ok")
        session.add(account)
        session.flush()
        dialog = Dialog(
            account_id=account.id,
            peer_id=202,
            title="Собеседник",
            last_message_vk_id=vk_id,
            last_message_preview=body,
            last_message_outgoing=outgoing,
            last_message_deleted=False,
            last_message_at=datetime(2026, 8, 27, 12, 0, 0),
        )
        session.add(dialog)
        session.flush()
        message = Message(
            account_id=account.id,
            dialog_id=dialog.id,
            vk_message_id=vk_id,
            from_id=account.vk_user_id if outgoing else 202,
            outgoing=outgoing,
            body=body,
            sent_at=datetime(2026, 8, 27, 12, 0, 0),
            deleted=False,
        )
        session.add(message)
        session.commit()
        return account.id, dialog.id


def test_history_sync_keeps_known_text_when_latest_incoming_becomes_deleted(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'deleted-incoming.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    account_id, dialog_id = seed_last_message(engine, outgoing=False, body="старый входящий")
    service = make_service(tmp_path, engine)

    service._store_history_page(
        dialog_id,
        account_id,
        {
            "items": [{
                "id": 555,
                "date": 1_777_000_000,
                "from_id": 202,
                "out": 0,
                "deleted": 1,
                "text": "",
                "attachments": [],
            }],
            "in_read": 555,
            "out_read": 0,
        },
    )

    with Session(engine) as session:
        message = session.query(Message).filter_by(dialog_id=dialog_id, vk_message_id=555).one()
        dialog = session.get(Dialog, dialog_id)
        assert message.deleted is True
        assert message.body == "старый входящий"
        assert dialog is not None
        assert dialog.last_message_deleted is True
        assert dialog.last_message_outgoing is False
        assert dialog.last_message_preview == "старый входящий"


async def test_deleting_latest_outgoing_updates_dialog_preview_immediately(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'deleted-outgoing.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    _account_id, dialog_id = seed_last_message(engine, outgoing=True, body="мой старый текст")

    async def runner(_account_id, operation, **_kwargs):
        class Client:
            async def delete_message(self, message_id: int, *, delete_for_all: bool = True):
                return VkActionResult(AttemptState.SENT, object_id=message_id)
        return await operation(Client())

    service = make_service(tmp_path, engine, runner)
    result = await service.delete_message(dialog_id, 555, delete_for_all=True)
    assert result["ok"] is True

    with Session(engine) as session:
        dialog = session.get(Dialog, dialog_id)
        message = session.query(Message).filter_by(dialog_id=dialog_id, vk_message_id=555).one()
        assert message.deleted is True
        assert dialog is not None
        assert dialog.last_message_deleted is True
        assert dialog.last_message_outgoing is True
        assert dialog.last_message_preview == ""
