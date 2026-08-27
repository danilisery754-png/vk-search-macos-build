from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.enums import AttemptState, WorkItemState
from app.db.base import Base
from app.db.models import Account, Community, Message, Result, Run, WorkItem
from app.services.inbox import InboxService
from app.services.processor import WorkProcessor
from app.services.queue import QueueRepository
from app.services.runs import RunService
from app.services.settings import SettingsService
from app.vk.client import VkActionResult
from app.workers.supervisor import WorkerSupervisor


def make_engine(tmp_path, name: str):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / name}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return engine


class FakeSettings:
    def all(self):
        return {
            "max_groups_per_account": 50,
            "message_texts": ["Привет"],
            "suggested_post_texts": ["Привет"],
            "retry_min_attempts": 1,
            "retry_max_attempts": 4,
            "delay_mode": "random",
            "delay_min_seconds": 15,
            "delay_max_seconds": 30,
        }


class FakeAccounts:
    def get_token(self, account_id):
        return "token"


class CountingClient:
    def __init__(self, message_result, suggested_result):
        self.message_result = message_result
        self.suggested_result = suggested_result
        self.message_calls = 0
        self.suggested_calls = 0

    async def send_community_message(self, community_id, text, key):
        self.message_calls += 1
        return self.message_result

    async def send_suggested_post(self, community_id, text):
        self.suggested_calls += 1
        return self.suggested_result

    async def aclose(self):
        pass


def seed_work(engine):
    with Session(engine) as session:
        account = Account(vk_user_id=100, first_name="Тест", note="Основной акк", enabled=True, auth_status="ok")
        group = Community(vk_id=200, name="Группа", canonical_url="https://vk.com/club200")
        run = Run(state="running", original_count=1)
        session.add_all([account, group, run])
        session.flush()
        item = WorkItem(run_id=run.id, community_id=group.id, state=WorkItemState.WAITING)
        session.add(item)
        session.commit()
        return account.id, item.id


def test_startup_suspends_persisted_running_and_waiting_runs(tmp_path):
    engine = make_engine(tmp_path, "startup.sqlite3")
    with Session(engine) as session:
        session.add_all([Run(state="running"), Run(state="waiting_limit"), Run(state="draft")])
        session.commit()

    service = RunService(engine, FakeSettings())
    changed = service.suspend_unconfirmed_on_startup()

    assert changed == 2
    with Session(engine) as session:
        states = list(session.scalars(select(Run.state).order_by(Run.id)).all())
    assert states == ["paused", "paused", "draft"]


async def test_supervisor_never_implicitly_resumes_waiting_limit(tmp_path):
    engine = make_engine(tmp_path, "supervisor.sqlite3")

    class Runs:
        calls = 0

        def try_resume_waiting(self):
            self.calls += 1

        def finish_if_idle(self, run_id):
            return None

    class Processor:
        async def process_next(self, account_id, owner):
            raise AssertionError("processor must not run without explicit start")

    class Logs:
        def add(self, *args, **kwargs):
            pass

    runs = Runs()
    supervisor = WorkerSupervisor(engine, Processor(), FakeSettings(), runs, Logs())
    supervisor.start()
    await asyncio.sleep(0.05)
    await supervisor.stop()

    assert runs.calls == 0


async def test_successful_private_message_is_not_duplicated_into_suggested_post(tmp_path):
    engine = make_engine(tmp_path, "fallback.sqlite3")
    account_id, item_id = seed_work(engine)
    sent = VkActionResult(AttemptState.SENT, object_id=123)
    forbidden = VkActionResult(AttemptState.FAILED_FINAL, error_code=214, error_class="suggested_post_forbidden", reason="нет предложки")
    client = CountingClient(sent, forbidden)
    processor = WorkProcessor(
        engine,
        QueueRepository(engine),
        FakeAccounts(),
        FakeSettings(),
        client_factory=lambda _: client,
    )

    worked = await processor.process_next(account_id, "worker")

    assert worked is True
    assert client.message_calls == 1
    assert client.suggested_calls == 0
    with Session(engine) as session:
        result = session.scalar(select(Result).where(Result.work_item_id == item_id))
        item = session.get(WorkItem, item_id)
        assert result is not None
        assert result.destination == "ЛС"
        assert item.state is WorkItemState.SUCCESS


async def test_suggested_post_is_fallback_when_private_messages_are_unavailable(tmp_path):
    engine = make_engine(tmp_path, "fallback-2.sqlite3")
    account_id, item_id = seed_work(engine)
    no_messages = VkActionResult(AttemptState.FAILED_FINAL, error_code=901, error_class="messages_forbidden", reason="ЛС недоступны")
    sent = VkActionResult(AttemptState.SENT, object_id=456)
    client = CountingClient(no_messages, sent)
    processor = WorkProcessor(
        engine,
        QueueRepository(engine),
        FakeAccounts(),
        FakeSettings(),
        client_factory=lambda _: client,
    )

    await processor.process_next(account_id, "worker")

    assert client.message_calls == 1
    assert client.suggested_calls == 1
    with Session(engine) as session:
        result = session.scalar(select(Result).where(Result.work_item_id == item_id))
        assert result is not None
        assert result.destination == "Предложка"


def test_empty_reply_payload_is_exposed_as_null_not_fake_reply(tmp_path):
    engine = make_engine(tmp_path, "reply.sqlite3")
    with Session(engine) as session:
        account = Account(vk_user_id=1, enabled=True, auth_status="ok")
        from app.db.models import Dialog
        dialog = Dialog(account_id=1, peer_id=-2)
        session.add(account)
        session.flush()
        dialog.account_id = account.id
        session.add(dialog)
        session.flush()
        message = Message(
            account_id=account.id,
            dialog_id=dialog.id,
            vk_message_id=10,
            from_id=-2,
            outgoing=False,
            body="Обычное сообщение",
            sent_at=datetime.utcnow(),
            reply_json="{}",
        )
        session.add(message)
        session.commit()
        session.refresh(message)
        public = InboxService._message_public(InboxService.__new__(InboxService), message)

    assert public["reply_message"] is None


def test_settings_have_retry_range_and_ui_scale(tmp_path):
    engine = make_engine(tmp_path, "settings.sqlite3")
    settings = SettingsService(engine)
    values = settings.all()
    assert values["retry_min_attempts"] >= 1
    assert values["retry_min_attempts"] <= values["retry_max_attempts"]
    assert 0.75 <= float(values["ui_scale"]) <= 1.5

    with pytest.raises(ValueError):
        settings.update({"retry_min_attempts": 5, "retry_max_attempts": 2})
