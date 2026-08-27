from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import WorkItemState
from app.db.base import Base
from app.db.models import Account, Community, Run, SendAttempt, WorkItem
from app.services.queue import QueueRepository


@pytest.fixture()
def engine(tmp_path):
    db_path = tmp_path / "queue.sqlite3"
    value = create_engine(
        f"sqlite+pysqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(value)
    return value


def seed_one_item(engine) -> tuple[int, int, int]:
    with Session(engine) as session:
        account = Account(vk_user_id=101, first_name="Сергей", last_name="Иванов", enabled=True)
        community = Community(vk_id=500, canonical_url="https://vk.com/club500")
        run = Run(state="running")
        session.add_all([account, community, run])
        session.flush()
        item = WorkItem(
            run_id=run.id,
            community_id=community.id,
            assigned_account_id=account.id,
            state=WorkItemState.ASSIGNED,
        )
        session.add(item)
        session.commit()
        return account.id, run.id, item.id


def test_atomic_claim_cannot_return_one_item_to_two_workers(engine):
    account_id, _, item_id = seed_one_item(engine)
    queue = QueueRepository(engine)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(lambda owner: queue.claim_next(account_id, owner), ["worker-a", "worker-b"]))

    assert sorted(value.id for value in claimed if value is not None) == [item_id]


def test_expired_processing_item_requires_reconciliation_not_blind_resend(engine):
    account_id, _, item_id = seed_one_item(engine)
    queue = QueueRepository(engine)
    claimed = queue.claim_next(account_id, "worker-a", lease_seconds=1)
    assert claimed and claimed.id == item_id

    with Session(engine) as session:
        item = session.get(WorkItem, item_id)
        item.lease_expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        session.commit()

    assert queue.recover_expired() == 1
    with Session(engine) as session:
        assert session.get(WorkItem, item_id).state == WorkItemState.RECONCILE_REQUIRED


def test_community_is_unique_inside_run_but_allowed_in_future_run(engine):
    account_id, run_id, _ = seed_one_item(engine)
    with Session(engine) as session:
        community_id = session.scalar(select(Community.id).where(Community.vk_id == 500))
        session.add(WorkItem(run_id=run_id, community_id=community_id, assigned_account_id=account_id))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        later = Run(state="created")
        session.add(later)
        session.flush()
        session.add(WorkItem(run_id=later.id, community_id=community_id, assigned_account_id=account_id))
        session.commit()


def test_send_attempt_idempotency_key_is_unique(engine):
    _, _, item_id = seed_one_item(engine)
    with Session(engine) as session:
        session.add(SendAttempt(work_item_id=item_id, direction="message", idempotency_key="same-key"))
        session.commit()
        session.add(SendAttempt(work_item_id=item_id, direction="message", idempotency_key="same-key"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_disabling_account_returns_only_unstarted_items_to_pool(engine):
    account_id, run_id, processing_id = seed_one_item(engine)
    with Session(engine) as session:
        community = Community(vk_id=501, canonical_url="https://vk.com/club501")
        session.add(community)
        session.flush()
        waiting = WorkItem(
            run_id=run_id,
            community_id=community.id,
            assigned_account_id=account_id,
            state=WorkItemState.ASSIGNED,
        )
        session.add(waiting)
        session.commit()
        waiting_id = waiting.id

    queue = QueueRepository(engine)
    queue.claim_next(account_id, "worker-a")
    assert queue.release_unstarted(account_id) == 1

    with Session(engine) as session:
        assert session.get(WorkItem, processing_id).state == WorkItemState.PROCESSING
        returned = session.get(WorkItem, waiting_id)
        assert returned.state == WorkItemState.WAITING
        assert returned.assigned_account_id is None
        assert session.scalar(select(func.count()).select_from(WorkItem)) == 2

