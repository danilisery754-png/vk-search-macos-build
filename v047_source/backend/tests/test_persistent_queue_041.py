from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.enums import WorkItemState
from app.db.base import Base
from app.db.models import Account, AccountQuota, Community, Run, WorkItem
from app.services.queue import QueueRepository
from app.services.worklist import WorkListService


@pytest.fixture()
def engine(tmp_path):
    value = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'queue041.sqlite3'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(value)
    return value


def seed_waiting(engine, *, accounts: int, groups: int) -> tuple[int, list[int]]:
    with Session(engine) as session:
        run = Run(state="running")
        session.add(run)
        account_ids = []
        for index in range(accounts):
            account = Account(vk_user_id=1000 + index, enabled=True, auth_status="ok", first_name=f"A{index}")
            session.add(account)
            session.flush()
            account_ids.append(account.id)
        for index in range(groups):
            community = Community(vk_id=5000 + index, canonical_url=f"https://vk.com/club{5000 + index}")
            session.add(community)
            session.flush()
            session.add(WorkItem(run_id=run.id, community_id=community.id, state=WorkItemState.WAITING))
        session.commit()
        return run.id, account_ids


def test_three_accounts_limit_ten_claim_only_thirty_of_one_hundred(engine):
    run_id, account_ids = seed_waiting(engine, accounts=3, groups=100)
    queue = QueueRepository(engine)
    now = datetime(2026, 8, 26, 12, 0, 0)

    claimed_ids: list[int] = []
    for account_id in account_ids:
        for _ in range(11):
            claimed = queue.claim_next(account_id, f"worker-{account_id}", daily_limit=10, now=now)
            if claimed is None:
                break
            claimed_ids.append(claimed.id)
            queue.finalize(claimed.id, WorkItemState.SUCCESS)

    assert len(claimed_ids) == 30
    with Session(engine) as session:
        waiting = session.scalar(
            select(func.count()).select_from(WorkItem).where(
                WorkItem.run_id == run_id,
                WorkItem.state == WorkItemState.WAITING,
            )
        )
        assert waiting == 70
        quotas = list(session.scalars(select(AccountQuota).order_by(AccountQuota.account_id)).all())
        assert [row.consumed for row in quotas] == [10, 10, 10]


def test_concurrent_claims_cannot_oversubscribe_one_remaining_quota_slot(engine):
    _, account_ids = seed_waiting(engine, accounts=1, groups=2)
    queue = QueueRepository(engine)
    now = datetime(2026, 8, 26, 13, 0, 0)
    account_id = account_ids[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(
            lambda owner: queue.claim_next(account_id, owner, daily_limit=1, now=now),
            ["a", "b"],
        ))

    assert sum(item is not None for item in values) == 1
    with Session(engine) as session:
        assert session.get(AccountQuota, account_id).consumed == 1
        assert session.scalar(
            select(func.count()).select_from(WorkItem).where(WorkItem.state == WorkItemState.WAITING)
        ) == 1


def test_retry_of_already_counted_group_does_not_consume_quota_twice(engine):
    _, account_ids = seed_waiting(engine, accounts=1, groups=2)
    queue = QueueRepository(engine)
    now = datetime(2026, 8, 26, 14, 0, 0)
    account_id = account_ids[0]

    first = queue.claim_next(account_id, "worker", daily_limit=1, now=now)
    assert first is not None
    assert queue.schedule_retry(first.id, delay_seconds=0, reason="retry")

    retried = queue.claim_next(account_id, "worker", daily_limit=1, now=now)
    assert retried is not None
    assert retried.id == first.id
    with Session(engine) as session:
        assert session.get(AccountQuota, account_id).consumed == 1
        assert session.scalar(
            select(func.count()).select_from(WorkItem).where(WorkItem.state == WorkItemState.WAITING)
        ) == 1


@pytest.mark.asyncio
async def test_replace_import_removes_only_not_started_tail_and_preserves_in_flight(engine):
    with Session(engine) as session:
        run = Run(state="running")
        old_waiting_group = Community(vk_id=7001, canonical_url="https://vk.com/club7001")
        in_flight_group = Community(vk_id=7002, canonical_url="https://vk.com/club7002")
        session.add_all([run, old_waiting_group, in_flight_group])
        session.flush()
        waiting = WorkItem(run_id=run.id, community_id=old_waiting_group.id, state=WorkItemState.WAITING)
        processing = WorkItem(
            run_id=run.id,
            community_id=in_flight_group.id,
            state=WorkItemState.PROCESSING,
            started_at=datetime(2026, 8, 26, 10, 0, 0),
        )
        session.add_all([waiting, processing])
        session.commit()
        run_id = run.id
        processing_id = processing.id

    service = WorkListService(engine, accounts=object())
    summary = await service.import_text("https://vk.com/club7003", mode="replace_waiting")

    assert summary.added == 1
    assert summary.replaced == 1
    with Session(engine) as session:
        rows = list(session.scalars(select(WorkItem).where(WorkItem.run_id == run_id).order_by(WorkItem.id)).all())
        assert session.get(WorkItem, processing_id) is not None
        assert len(rows) == 2
        assert {session.get(Community, row.community_id).vk_id for row in rows} == {7002, 7003}


@pytest.mark.asyncio
async def test_historical_contact_does_not_blacklist_same_group_in_later_run(engine):
    with Session(engine) as session:
        community = Community(vk_id=8001, canonical_url="https://vk.com/club8001")
        old_run = Run(state="completed")
        session.add_all([community, old_run])
        session.flush()
        community_id = community.id
        session.add(WorkItem(
            run_id=old_run.id,
            community_id=community_id,
            state=WorkItemState.SUCCESS,
            completed_at=datetime(2026, 8, 25, 12, 0, 0),
        ))
        session.commit()
        old_run_id = old_run.id

    service = WorkListService(engine, accounts=object())
    summary = await service.import_text("https://vk.com/club8001", mode="append")

    assert summary.added == 1
    with Session(engine) as session:
        run_ids = list(session.scalars(
            select(WorkItem.run_id).where(WorkItem.community_id == community_id).order_by(WorkItem.run_id)
        ).all())
        assert len(run_ids) == 2
        assert old_run_id in run_ids
        assert run_ids[-1] != old_run_id
