from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Account, Dialog, Message
from app.services.inbox import InboxService


class TokenAccounts:
    def __init__(self, tokens):
        self.tokens = tokens

    def get_token(self, account_id):
        return self.tokens[account_id]


class PagingHistoryClient:
    def __init__(self, token, calls):
        self.token = token
        self.calls = calls

    async def get_history(self, peer_id, *, offset=0, count=100):
        self.calls.append((peer_id, offset, count))
        available = max(0, min(count, 300 - offset))
        items = [
            {
                "id": 1000 - offset - index,
                "from_id": 500,
                "out": 0,
                "date": 1700000000 - offset - index,
                "text": f"message {offset + index}",
            }
            for index in range(available)
        ]
        return {"count": 800, "in_read": 2000, "out_read": 2000, "items": items}, None

    async def aclose(self):
        pass


def seed(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'paging.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(vk_user_id=1, first_name="Иван", note="Основной", avatar_url="https://example/avatar.jpg")
        session.add(account)
        session.flush()
        dialog = Dialog(account_id=account.id, peer_id=-500, title="Группа")
        session.add(dialog)
        session.commit()
        return engine, account.id, dialog.id


async def test_sync_dialog_chunks_300_messages_into_vk_safe_pages(tmp_path):
    engine, account_id, dialog_id = seed(tmp_path)
    calls = []
    inbox = InboxService(
        engine,
        TokenAccounts({account_id: "token"}),
        client_factory=lambda token: PagingHistoryClient(token, calls),
    )

    result = await inbox.sync_dialog(dialog_id, offset=0, count=300)

    assert calls == [(-500, 0, 200), (-500, 200, 100)]
    assert result == {
        "ok": True,
        "messages": 300,
        "fetched": 300,
        "total": 800,
        "next_offset": 300,
        "has_more": True,
    }
    with Session(engine) as session:
        assert session.query(Message).count() == 300


def test_list_messages_exposes_reply_identity_and_stable_older_cursor(tmp_path):
    engine, account_id, dialog_id = seed(tmp_path)
    with Session(engine) as session:
        for index in range(420):
            session.add(Message(
                account_id=account_id,
                dialog_id=dialog_id,
                vk_message_id=index + 1,
                from_id=500,
                outgoing=False,
                body=f"local {index + 1}",
                sent_at=datetime.fromtimestamp(1700000000 + index),
                is_read=True,
            ))
        session.commit()
    inbox = InboxService(engine, TokenAccounts({account_id: "token"}))

    payload = inbox.list_messages(dialog_id, limit=300)

    assert payload["reply_account"] == {
        "id": account_id,
        "name": "Основной",
        "note": "Основной",
        "avatar_url": "https://example/avatar.jpg",
    }
    assert payload["dialog"]["can_write"] is True
    assert payload["local_total"] == 420
    assert payload["has_older_local"] is True
    assert len(payload["messages"]) == 300
    oldest = payload["next_before_vk_message_id"]
    assert oldest == 121

    older = inbox.list_messages(dialog_id, limit=200, before_vk_message_id=oldest)
    assert len(older["messages"]) == 120
    assert max(row["vk_message_id"] for row in older["messages"]) < oldest
    assert older["has_older_local"] is False
