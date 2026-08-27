from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.enums import AttemptState, WorkItemState
from app.db.base import Base
from app.db.models import Account, Community, Dialog, Run, WorkItem
from app.services.inbox import InboxService
from app.services.processor import WorkProcessor
from app.services.queue import QueueRepository
from app.services.worklist import WorkListService
from app.vk.client import VkActionResult, VkCommunity


class RefreshAwareAccounts:
    def __init__(self, client):
        self.client = client
        self.run_calls: list[int] = []

    def get_token(self, _account_id):
        raise AssertionError("service bypassed AccountService.run_vk")

    async def run_vk(self, account_id, operation, *, client_factory=None):
        self.run_calls.append(account_id)
        return await operation(self.client)


class ProcessorClient:
    async def send_community_message(self, _community_id, _text, _key):
        return VkActionResult(AttemptState.SENT, object_id=10)

    async def send_suggested_post(self, _community_id, _text):
        return VkActionResult(AttemptState.FAILED_FINAL, reason="closed")


class Settings:
    def all(self):
        return {
            "message_text": "old",
            "suggested_post_text": "old",
            "message_texts": ["hello"],
            "suggested_post_texts": ["hello"],
            "retry_max_attempts": 2,
        }


def _seed_processor(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'processor-refresh.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(vk_user_id=101, first_name="A", enabled=True, auth_status="ok")
        community = Community(vk_id=202, canonical_url="https://vk.com/club202")
        run = Run(state="running")
        session.add_all([account, community, run])
        session.flush()
        session.add(
            WorkItem(
                run_id=run.id,
                community_id=community.id,
                assigned_account_id=account.id,
                state=WorkItemState.ASSIGNED,
            )
        )
        session.commit()
        return engine, account.id


@pytest.mark.asyncio
async def test_processor_routes_each_vk_direction_through_account_refresh_wrapper(tmp_path):
    engine, account_id = _seed_processor(tmp_path)
    accounts = RefreshAwareAccounts(ProcessorClient())
    processor = WorkProcessor(engine, QueueRepository(engine), accounts, Settings())

    assert await processor.process_next(account_id, "worker") is True
    assert accounts.run_calls == [account_id, account_id]


class InboxClient:
    async def get_history(self, _peer_id, *, offset=0, count=100):
        return {"items": [], "in_read": 0, "out_read": 0}, None


@pytest.mark.asyncio
async def test_inbox_history_uses_account_refresh_wrapper(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'inbox-refresh.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(vk_user_id=303, first_name="B", auth_status="ok")
        session.add(account)
        session.flush()
        dialog = Dialog(account_id=account.id, peer_id=-404, title="G", last_message_at=datetime.now())
        session.add(dialog)
        session.commit()
        account_id, dialog_id = account.id, dialog.id
    accounts = RefreshAwareAccounts(InboxClient())
    inbox = InboxService(engine, accounts)

    assert await inbox.sync_dialog(dialog_id) == {"ok": True, "messages": 0, "fetched": 0, "total": 0, "next_offset": 0, "has_more": False}
    assert accounts.run_calls == [account_id]


class ResolveClient:
    async def resolve_communities(self, lookups):
        assert lookups == ["example"]
        return [VkCommunity(505, "example", "Example", "https://vk.com/example")], None


@pytest.mark.asyncio
async def test_worklist_resolution_uses_account_refresh_wrapper(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'worklist-refresh.sqlite3'}")
    Base.metadata.create_all(engine)
    accounts = RefreshAwareAccounts(ResolveClient())
    service = WorkListService(engine, accounts)
    monkeypatch.setattr(service, "_first_authorized_account_id", lambda: 606)

    summary = await service.import_text("https://vk.com/example")

    assert summary.added == 1
    assert summary.unresolved == []
    assert accounts.run_calls == [606]
