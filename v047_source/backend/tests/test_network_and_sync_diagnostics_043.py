import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Account
from app.vk.client import VkApiClient
from app.workers.inbox_sync import InboxSyncWorker


@pytest.mark.asyncio
async def test_vk_read_timeout_has_nonempty_specific_reason():
    async def handler(request):
        raise httpx.ReadTimeout("", request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = VkApiClient("token", http=http)
        result = await client.validate_identity()
    assert result.error_class == "network_timeout"
    assert "таймаут" in result.reason.lower()
    assert "vk" in result.reason.lower()


class FakeInbox:
    def __init__(self):
        self.ok = False
    async def sync_account(self, account_id):
        if self.ok:
            return {"ok": True, "dialogs": 0}
        return {"ok": False, "state": "temporary_error", "error": "VK слишком долго не отвечал (таймаут чтения)"}


class FakeSettings:
    def all(self):
        return {"inbox_sync_seconds": 30}


class FakeLogs:
    def __init__(self):
        self.rows = []
    def add(self, message, *, level="info", account_id=None, **kwargs):
        self.rows.append((level, account_id, message))


@pytest.mark.asyncio
async def test_repeated_sync_error_is_deduplicated_and_recovery_logged():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(vk_user_id=1, first_name="A", enabled=True, auth_status="ok"))
        session.commit()
    inbox = FakeInbox()
    logs = FakeLogs()
    worker = InboxSyncWorker(engine, inbox, FakeSettings(), logs)
    await worker.sync_once()
    await worker.sync_once()
    warnings = [row for row in logs.rows if row[0] == "warning"]
    assert len(warnings) == 1
    inbox.ok = True
    await worker.sync_once()
    assert any("восстановлена" in row[2].lower() for row in logs.rows)
