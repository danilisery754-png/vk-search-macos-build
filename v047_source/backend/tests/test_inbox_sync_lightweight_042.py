from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Account
from app.workers.inbox_sync import InboxSyncWorker


class FakeSettings:
    def all(self):
        return {"inbox_sync_seconds": 30}


class FakeLogs:
    def __init__(self):
        self.entries = []

    def add(self, message, **kwargs):
        self.entries.append((message, kwargs))


class LightweightInbox:
    def __init__(self):
        self.account_calls = []

    async def sync_account(self, account_id):
        self.account_calls.append(account_id)
        return {"ok": True, "dialogs": 1}

    def list_dialogs(self, **_kwargs):
        raise AssertionError("background sync must not enumerate unread dialog histories")

    async def sync_dialog(self, _dialog_id):
        raise AssertionError("background sync must not download dialog history")


class BlankErrorInbox:
    async def sync_account(self, _account_id):
        return {"ok": False, "error": "", "state": "auth_required"}


async def _engine_with_account(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'sync042.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=1, vk_user_id=1, enabled=True, auth_status="ok"))
        session.commit()
    return engine


async def test_background_sync_updates_dialog_list_only_and_never_fetches_history(tmp_path):
    engine = await _engine_with_account(tmp_path)
    inbox, logs = LightweightInbox(), FakeLogs()
    worker = InboxSyncWorker(engine, inbox, FakeSettings(), logs)

    result = await worker.sync_once()

    assert inbox.account_calls == [1]
    assert result == {"attempted": 1, "succeeded": 1, "failed": 0, "dialogs": 0}
    assert logs.entries == []


async def test_background_sync_never_logs_an_empty_error_message(tmp_path):
    engine = await _engine_with_account(tmp_path)
    logs = FakeLogs()
    worker = InboxSyncWorker(engine, BlankErrorInbox(), FakeSettings(), logs)

    result = await worker.sync_once()

    assert result["failed"] == 1
    assert len(logs.entries) == 1
    message = logs.entries[0][0]
    assert message != "Не удалось синхронизировать сообщения: "
    assert "повтор" in message.lower() or "авториза" in message.lower()
