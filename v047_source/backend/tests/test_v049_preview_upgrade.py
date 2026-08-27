from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Account, Dialog, Message
from app.services.accounts_v049 import AccountService
from app.services.inbox_v049_runtime import InboxService


def test_list_dialogs_uses_known_local_text_for_deleted_incoming_after_upgrade(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'preview-upgrade.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(vk_user_id=101, first_name="Иван", enabled=True, auth_status="ok")
        session.add(account)
        session.flush()
        dialog = Dialog(
            account_id=account.id,
            peer_id=202,
            title="Собеседник",
            last_message_vk_id=555,
            last_message_preview="",
            last_message_outgoing=False,
            last_message_deleted=True,
            last_message_at=datetime(2026, 8, 27, 12, 0, 0),
        )
        session.add(dialog)
        session.flush()
        session.add(Message(
            account_id=account.id,
            dialog_id=dialog.id,
            vk_message_id=555,
            from_id=202,
            outgoing=False,
            body="известный старый текст",
            sent_at=datetime(2026, 8, 27, 12, 0, 0),
            deleted=False,
        ))
        session.commit()

    profiles = tmp_path / "profiles"
    profiles.mkdir()
    accounts = AccountService(engine, profiles, tmp_path / "secret.key")
    rows = InboxService(engine, accounts).list_dialogs()

    assert len(rows) == 1
    assert rows[0]["last_message_deleted"] is True
    assert rows[0]["last_message_outgoing"] is False
    assert rows[0]["last_message_preview"] == "известный старый текст"
