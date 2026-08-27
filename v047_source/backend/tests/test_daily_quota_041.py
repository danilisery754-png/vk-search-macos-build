from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Account
from app.services.quota import QuotaService


class MutableSettings:
    def __init__(self, limit: int = 50):
        self.limit = limit

    def all(self):
        return {"max_groups_per_account": self.limit}


@pytest.fixture()
def engine(tmp_path):
    value = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'quota.sqlite3'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(value)
    return value


@pytest.fixture()
def account_id(engine):
    with Session(engine) as session:
        account = Account(vk_user_id=1001, first_name="Quota", enabled=True, auth_status="ok")
        session.add(account)
        session.commit()
        return account.id


def test_first_counted_action_opens_rolling_24h_window(engine, account_id):
    settings = MutableSettings(50)
    quota = QuotaService(engine, settings)
    now = datetime(2026, 8, 26, 18, 43, 0)

    before = quota.snapshot(account_id, now=now)
    assert before.consumed == 0
    assert before.available == 50
    assert before.window_started_at is None

    after = quota.reserve(account_id, now=now)
    assert after is not None
    assert after.consumed == 1
    assert after.available == 49
    assert after.window_started_at == now
    assert after.window_ends_at == now + timedelta(hours=24)


def test_limit_increase_exposes_only_delta_inside_same_window(engine, account_id):
    settings = MutableSettings(50)
    quota = QuotaService(engine, settings)
    now = datetime(2026, 8, 26, 12, 0, 0)

    for _ in range(50):
        assert quota.reserve(account_id, now=now) is not None
    assert quota.reserve(account_id, now=now) is None

    settings.limit = 51
    assert quota.snapshot(account_id, now=now).available == 1
    assert quota.reserve(account_id, now=now) is not None
    assert quota.reserve(account_id, now=now) is None

    settings.limit = 70
    assert quota.snapshot(account_id, now=now).available == 19
    for _ in range(19):
        assert quota.reserve(account_id, now=now) is not None
    assert quota.reserve(account_id, now=now) is None


def test_limit_decrease_does_not_rewrite_consumed_or_window(engine, account_id):
    settings = MutableSettings(50)
    quota = QuotaService(engine, settings)
    start = datetime(2026, 8, 26, 9, 15, 0)

    for _ in range(50):
        assert quota.reserve(account_id, now=start) is not None
    settings.limit = 40

    blocked = quota.snapshot(account_id, now=start + timedelta(hours=3))
    assert blocked.consumed == 50
    assert blocked.available == 0
    assert blocked.window_ends_at == start + timedelta(hours=24)
    assert quota.reserve(account_id, now=start + timedelta(hours=3)) is None

    expired = quota.snapshot(account_id, now=start + timedelta(hours=24, seconds=1))
    assert expired.consumed == 0
    assert expired.available == 40
    assert expired.window_started_at is None
    assert quota.reserve(account_id, now=start + timedelta(hours=24, seconds=1)) is not None


def test_reset_affects_only_selected_accounts_and_not_configured_limit(engine, account_id):
    settings = MutableSettings(7)
    quota = QuotaService(engine, settings)
    with Session(engine) as session:
        second = Account(vk_user_id=1002, first_name="Second", enabled=True, auth_status="ok")
        session.add(second)
        session.commit()
        second_id = second.id

    now = datetime(2026, 8, 26, 10, 0, 0)
    assert quota.reserve(account_id, now=now)
    assert quota.reserve(second_id, now=now)
    quota.reset([account_id])

    assert quota.snapshot(account_id, now=now).consumed == 0
    assert quota.snapshot(account_id, now=now).available == 7
    assert quota.snapshot(second_id, now=now).consumed == 1
    assert settings.limit == 7


def test_concurrent_reservations_cannot_oversubscribe_last_slot(engine, account_id):
    settings = MutableSettings(1)
    quota = QuotaService(engine, settings)
    now = datetime(2026, 8, 26, 11, 0, 0)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: quota.reserve(account_id, now=now), range(2)))

    assert sum(result is not None for result in results) == 1
    snapshot = quota.snapshot(account_id, now=now)
    assert snapshot.consumed == 1
    assert snapshot.available == 0
