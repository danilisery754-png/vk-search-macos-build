from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.enums import AttemptState
from app.db.base import Base
from app.db.models import Account, Dialog, Message
from app.services.inbox import InboxService
from app.vk.client import VkActionResult


class TokenAccounts:
    def __init__(self, tokens):
        self.tokens = tokens

    def get_token(self, account_id):
        return self.tokens[account_id]


class CaptureClient:
    def __init__(self, token, calls):
        self.token = token
        self.calls = calls

    async def send_message(self, peer_id, message, key):
        self.calls.append((self.token, peer_id, message))
        return VkActionResult(AttemptState.SENT, object_id=99)

    async def aclose(self):
        pass


class HistoryClient:
    def __init__(self, token, calls):
        self.token = token
        self.calls = calls

    async def get_history(self, peer_id, *, offset=0, count=100):
        self.calls.append(("history", self.token, peer_id, offset, count))
        return {
            "in_read": 11,
            "out_read": 21,
            "items": [
                {"id": 10, "from_id": 500, "out": 0, "date": 100, "text": "in read"},
                {"id": 12, "from_id": 500, "out": 0, "date": 101, "text": "in unread"},
                {"id": 20, "from_id": 1, "out": 1, "date": 102, "text": "out read"},
                {"id": 22, "from_id": 1, "out": 1, "date": 103, "text": "out unread"},
            ],
        }, None

    async def mark_as_read(self, peer_id):
        self.calls.append(("mark", self.token, peer_id))
        return VkActionResult(AttemptState.SENT, object_id=1)

    async def aclose(self):
        pass


class NoMarkersClient(HistoryClient):
    async def get_history(self, peer_id, *, offset=0, count=100):
        return {
            "items": [{"id": 88, "from_id": 500, "out": 0, "date": 100, "text": "still read"}],
        }, None


def seed(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'inbox.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        first = Account(vk_user_id=1, first_name="Первый", note="Покупка №1")
        second = Account(vk_user_id=2, first_name="Второй", note="Покупка №2")
        session.add_all([first, second])
        session.flush()
        one = Dialog(account_id=first.id, peer_id=-500, title="Одинаковая группа", last_message_at=datetime.now())
        two = Dialog(account_id=second.id, peer_id=-500, title="Одинаковая группа", last_message_at=datetime.now())
        session.add_all([one, two])
        session.commit()
        return engine, first.id, second.id, one.id, two.id


def test_same_peer_is_kept_separately_for_two_accounts(tmp_path):
    engine, first_id, second_id, _, _ = seed(tmp_path)
    inbox = InboxService(engine, TokenAccounts({}))

    rows = inbox.list_dialogs()

    assert len(rows) == 2
    assert {row["account_id"] for row in rows} == {first_id, second_id}
    assert {row["account_name"] for row in rows} == {"Покупка №1", "Покупка №2"}


async def test_reply_uses_token_of_dialog_owner(tmp_path):
    engine, first_id, second_id, _, second_dialog = seed(tmp_path)
    calls = []
    accounts = TokenAccounts({first_id: "token-one", second_id: "token-two"})
    inbox = InboxService(engine, accounts, client_factory=lambda token: CaptureClient(token, calls))

    result = await inbox.reply(second_dialog, "Ответ")

    assert calls == [("token-two", -500, "Ответ")]
    assert result["account_id"] == second_id


async def test_history_uses_vk_in_read_and_out_read_markers(tmp_path):
    engine, first_id, _, first_dialog, _ = seed(tmp_path)
    calls = []
    inbox = InboxService(
        engine,
        TokenAccounts({first_id: "token-one"}),
        client_factory=lambda token: HistoryClient(token, calls),
    )

    result = await inbox.sync_dialog(first_dialog)

    assert result == {"ok": True, "messages": 4, "fetched": 4, "total": 4, "next_offset": 4, "has_more": False}
    with Session(engine) as session:
        rows = session.query(Message).order_by(Message.vk_message_id).all()
        assert [(row.vk_message_id, row.is_read) for row in rows] == [
            (10, True),
            (12, False),
            (20, True),
            (22, False),
        ]


async def test_mark_read_uses_dialog_owner_token_and_clears_unread_totals(tmp_path):
    engine, first_id, _, first_dialog, _ = seed(tmp_path)
    calls = []
    with Session(engine) as session:
        dialog = session.get(Dialog, first_dialog)
        dialog.unread_count = 3
        account = session.get(Account, first_id)
        account.unread_count = 3
        session.add(Message(
            account_id=first_id,
            dialog_id=first_dialog,
            vk_message_id=77,
            from_id=500,
            outgoing=False,
            body="new",
            sent_at=datetime.now(),
            is_read=False,
        ))
        session.commit()
    inbox = InboxService(
        engine,
        TokenAccounts({first_id: "token-one"}),
        client_factory=lambda token: HistoryClient(token, calls),
    )

    result = await inbox.mark_read(first_dialog)

    assert result["ok"] is True
    assert calls == [("mark", "token-one", -500)]
    with Session(engine) as session:
        assert session.get(Dialog, first_dialog).unread_count == 0
        assert session.get(Account, first_id).unread_count == 0
        assert session.scalar(select(Message.is_read).where(Message.vk_message_id == 77)) is True


async def test_missing_read_markers_do_not_regress_known_local_state(tmp_path):
    engine, first_id, _, first_dialog, _ = seed(tmp_path)
    with Session(engine) as session:
        session.add(Message(
            account_id=first_id,
            dialog_id=first_dialog,
            vk_message_id=88,
            from_id=500,
            outgoing=False,
            body="already read",
            sent_at=datetime.now(),
            is_read=True,
        ))
        session.commit()
    inbox = InboxService(
        engine,
        TokenAccounts({first_id: "token-one"}),
        client_factory=lambda token: NoMarkersClient(token, []),
    )

    await inbox.sync_dialog(first_dialog)

    with Session(engine) as session:
        assert session.scalar(select(Message.is_read).where(Message.vk_message_id == 88)) is True

class ConversationClient:
    def __init__(self, token):
        self.token = token

    async def get_conversations(self, *, unread_only=False):
        return {
            "groups": [{"id": 500, "name": "Закрытая группа", "photo_100": ""}],
            "profiles": [],
            "items": [{
                "conversation": {
                    "peer": {"id": -500},
                    "unread_count": 0,
                    "can_write": {"allowed": False, "reason": 7},
                },
                "last_message": {"date": 100},
            }],
        }, None

    async def aclose(self):
        pass


async def test_sync_account_persists_dialog_write_capability(tmp_path):
    engine, first_id, _, _, _ = seed(tmp_path)
    inbox = InboxService(
        engine,
        TokenAccounts({first_id: "token-one"}),
        client_factory=ConversationClient,
    )

    result = await inbox.sync_account(first_id)

    assert result["ok"] is True
    with Session(engine) as session:
        dialog = session.scalar(select(Dialog).where(Dialog.account_id == first_id, Dialog.peer_id == -500))
        assert dialog is not None
        assert dialog.can_write is False
        assert dialog.write_disabled_reason == "7"
