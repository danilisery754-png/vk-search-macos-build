from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Account
from app.workers.inbox_sync import InboxSyncWorker


class FakeInbox:
    def __init__(self):
        self.calls = []

    async def sync_account(self, account_id):
        self.calls.append(account_id)
        if account_id == 1:
            raise RuntimeError("first failed")
        return {"ok": True}

    def list_dialogs(self, *, account_id, unread):
        assert unread is True
        return [{"id": 200}] if account_id == 2 else []

    async def sync_dialog(self, dialog_id):
        self.calls.append(("dialog", dialog_id))
        return {"ok": True}


class FakeSettings:
    def all(self):
        return {"inbox_sync_seconds": 30}


class FakeLogs:
    def __init__(self):
        self.entries = []

    def add(self, message, **kwargs):
        self.entries.append((message, kwargs))


async def test_sync_once_is_independent_and_one_account_failure_does_not_stop_next(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'sync.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            Account(id=1, vk_user_id=1, enabled=True, auth_status="ok"),
            Account(id=2, vk_user_id=2, enabled=True, auth_status="ok"),
            Account(id=3, vk_user_id=3, enabled=False, auth_status="ok"),
            Account(id=4, vk_user_id=4, enabled=True, auth_status="requires_login"),
        ])
        session.commit()
    inbox, logs = FakeInbox(), FakeLogs()
    worker = InboxSyncWorker(engine, inbox, FakeSettings(), logs)

    result = await worker.sync_once()

    assert inbox.calls == [1, 2]
    assert result == {"attempted": 2, "succeeded": 1, "failed": 1, "dialogs": 0}
    assert len(logs.entries) == 1
    assert logs.entries[0][1]["account_id"] == 1
