from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Account, Dialog
from app.services.accounts_v049 import AccountService
from app.services.inbox_v049_runtime import InboxService


async def test_sync_account_preserves_local_archive_on_new_message(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'archive-sync.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(vk_user_id=101, first_name="Иван", enabled=True, auth_status="ok")
        session.add(account)
        session.flush()
        account_id = account.id
        dialog = Dialog(
            account_id=account.id,
            peer_id=202,
            title="Собеседник",
            is_archived=True,
            unread_count=0,
        )
        session.add(dialog)
        session.commit()
        dialog_id = dialog.id

    class Client:
        async def get_conversations(self, *, unread_only=False):
            return {
                "profiles": [{"id": 202, "first_name": "Пётр", "last_name": "Петров"}],
                "groups": [],
                "items": [{
                    "conversation": {
                        "peer": {"id": 202},
                        "unread_count": 5,
                        "can_write": {"allowed": True},
                    },
                    "last_message": {
                        "id": 700,
                        "date": 1_700_000_100,
                        "out": 0,
                        "text": "новое входящее",
                        "attachments": [],
                    },
                }],
            }

    async def runner(_account_id, operation, **_kwargs):
        return await operation(Client()), None

    profiles = tmp_path / "profiles"
    profiles.mkdir()
    accounts = AccountService(engine, profiles, tmp_path / "secret.key")
    accounts.run_vk = runner  # type: ignore[method-assign]
    service = InboxService(engine, accounts)

    result = await service.sync_account(account_id)
    assert result["ok"] is True

    with Session(engine) as session:
        dialog = session.get(Dialog, dialog_id)
        assert dialog is not None
        assert dialog.is_archived is True
        assert dialog.unread_count == 5
        assert dialog.last_message_preview == "новое входящее"

    assert service.list_dialogs() == []
    archived = service.list_dialogs(archived=True)
    assert [row["id"] for row in archived] == [dialog_id]
    assert archived[0]["last_message_preview"] == "новое входящее"
