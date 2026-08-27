from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.enums import AttemptState, WorkItemState
from app.db.base import Base
from app.db.models import Account, AccountQuota, Community, Run, WorkItem
from app.services.processor import WorkProcessor
from app.services.queue import QueueRepository
from app.vk.client import VkActionResult
from app.workers.supervisor import WorkerSupervisor


class FakeAccounts:
    def get_token(self, account_id):
        return "token"


class QuotaSettings:
    def __init__(self, limit: int = 1):
        self.limit = limit

    def all(self):
        return {
            "max_groups_per_account": self.limit,
            "message_texts": ["Тест"],
            "suggested_post_texts": ["Тест"],
            "retry_max_attempts": 1,
            "delay_mode": "fixed",
            "delay_seconds": 0,
        }


class SuccessClient:
    async def send_community_message(self, community_id, text, key):
        return VkActionResult(AttemptState.SENT, object_id=101)

    async def send_suggested_post(self, community_id, text):
        return VkActionResult(AttemptState.SENT, object_id=202)

    async def aclose(self):
        pass


def seed_waiting(tmp_path, *, groups: int = 2):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'worker-quota.sqlite3'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(vk_user_id=41, first_name="Quota", enabled=True, auth_status="ok")
        run = Run(state="running")
        session.add_all([account, run])
        session.flush()
        for index in range(groups):
            community = Community(
                vk_id=9000 + index,
                canonical_url=f"https://vk.com/club{9000 + index}",
            )
            session.add(community)
            session.flush()
            session.add(
                WorkItem(
                    run_id=run.id,
                    community_id=community.id,
                    state=WorkItemState.WAITING,
                )
            )
        session.commit()
        return engine, account.id, run.id


async def test_processor_claims_shared_waiting_items_through_daily_quota(tmp_path):
    engine, account_id, run_id = seed_waiting(tmp_path, groups=2)
    settings = QuotaSettings(limit=1)
    processor = WorkProcessor(
        engine,
        QueueRepository(engine),
        FakeAccounts(),
        settings,
        client_factory=lambda _: SuccessClient(),
    )

    assert await processor.process_next(account_id, "worker") is True
    assert await processor.process_next(account_id, "worker") is False

    with Session(engine) as session:
        assert session.get(AccountQuota, account_id).consumed == 1
        assert session.scalar(
            select(func.count()).select_from(WorkItem).where(
                WorkItem.run_id == run_id,
                WorkItem.state == WorkItemState.WAITING,
            )
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(WorkItem).where(
                WorkItem.run_id == run_id,
                WorkItem.state == WorkItemState.SUCCESS,
            )
        ) == 1


class FakeRuns:
    def __init__(self):
        self.resume_checks = 0

    def try_resume_waiting(self):
        self.resume_checks += 1
        return None

    def finish_if_idle(self, run_id):
        return None


class FakeProcessor:
    async def process_next(self, account_id, owner):
        return False


class FakeLogs:
    def add(self, *args, **kwargs):
        pass


async def test_supervisor_checks_persisted_waiting_limit_for_automatic_resume(tmp_path):
    engine, account_id, run_id = seed_waiting(tmp_path, groups=1)
    start = datetime.utcnow() - timedelta(hours=25)
    with Session(engine) as session:
        run = session.get(Run, run_id)
        run.state = "waiting_limit"
        session.add(
            AccountQuota(
                account_id=account_id,
                window_started_at=start,
                window_ends_at=start + timedelta(hours=24),
                consumed=1,
            )
        )
        session.commit()

    runs = FakeRuns()
    supervisor = WorkerSupervisor(
        engine,
        FakeProcessor(),
        QuotaSettings(limit=1),
        runs,
        FakeLogs(),
    )
    supervisor.start()
    await asyncio.sleep(0.05)
    await supervisor.stop()

    assert runs.resume_checks >= 1
