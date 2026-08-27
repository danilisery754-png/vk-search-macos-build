from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.enums import WorkItemState
from app.db.base import Base
from app.db.models import Account, AccountQuota, Community, Run, WorkItem
from app.services.runs import RunService
from app.services.settings import SettingsService


def make_engine(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'run-quota.sqlite3'}")
    Base.metadata.create_all(engine)
    return engine


def seed(engine, *, groups: int = 2, account_count: int = 1):
    with Session(engine) as session:
        run = Run(state="draft")
        session.add(run)
        accounts = []
        for index in range(account_count):
            account = Account(vk_user_id=100 + index, enabled=True, auth_status="ok")
            session.add(account)
            session.flush()
            accounts.append(account.id)
        for index in range(groups):
            community = Community(vk_id=9000 + index, canonical_url=f"https://vk.com/club{9000 + index}")
            session.add(community)
            session.flush()
            session.add(WorkItem(run_id=run.id, community_id=community.id, state=WorkItemState.WAITING))
        session.commit()
        return run.id, accounts


def test_start_keeps_large_list_in_shared_waiting_pool(tmp_path):
    engine = make_engine(tmp_path)
    run_id, _ = seed(engine, groups=100, account_count=3)
    settings = SettingsService(engine)
    settings.update({"max_groups_per_account": 10})

    started = RunService(engine, settings).start()

    assert started["run_id"] == run_id
    assert started["state"] == "running"
    with Session(engine) as session:
        items = list(session.scalars(select(WorkItem).where(WorkItem.run_id == run_id)).all())
        assert all(item.state == WorkItemState.WAITING for item in items)
        assert all(item.assigned_account_id is None for item in items)
        assert session.get(Run, run_id).original_count == 100


def test_waiting_items_only_become_waiting_limit_when_all_accounts_are_blocked(tmp_path):
    engine = make_engine(tmp_path)
    run_id, account_ids = seed(engine, groups=3, account_count=2)
    settings = SettingsService(engine)
    settings.update({"max_groups_per_account": 1})
    service = RunService(engine, settings)
    service.start()
    start = datetime(2026, 8, 26, 12, 0, 0)

    with Session(engine) as session:
        for account_id in account_ids:
            session.add(AccountQuota(
                account_id=account_id,
                window_started_at=start,
                window_ends_at=start + timedelta(hours=24),
                consumed=1,
            ))
        session.commit()

    state = service.finish_if_idle(run_id, now=start + timedelta(hours=1))

    assert state is not None
    assert state["state"] == "waiting_limit"
    with Session(engine) as session:
        assert session.get(Run, run_id).state == "waiting_limit"


def test_waiting_items_do_not_enter_waiting_limit_when_capacity_exists(tmp_path):
    engine = make_engine(tmp_path)
    run_id, _ = seed(engine, groups=1, account_count=1)
    settings = SettingsService(engine)
    settings.update({"max_groups_per_account": 5})
    service = RunService(engine, settings)
    service.start()

    assert service.finish_if_idle(run_id, now=datetime(2026, 8, 26, 10, 0, 0)) is None
    with Session(engine) as session:
        assert session.get(Run, run_id).state == "running"


def test_waiting_limit_run_resumes_after_its_persisted_window_expires(tmp_path):
    engine = make_engine(tmp_path)
    run_id, account_ids = seed(engine, groups=1, account_count=1)
    settings = SettingsService(engine)
    settings.update({"max_groups_per_account": 1})
    service = RunService(engine, settings)
    service.start()
    start = datetime(2026, 8, 26, 9, 0, 0)
    with Session(engine) as session:
        session.add(AccountQuota(
            account_id=account_ids[0],
            window_started_at=start,
            window_ends_at=start + timedelta(hours=24),
            consumed=1,
        ))
        session.get(Run, run_id).state = "waiting_limit"
        session.commit()

    blocked = service.try_resume_waiting(now=start + timedelta(hours=23))
    assert blocked is None
    resumed = service.try_resume_waiting(now=start + timedelta(hours=24, seconds=1))

    assert resumed is not None
    assert resumed["run_id"] == run_id
    assert resumed["state"] == "running"
    with Session(engine) as session:
        assert session.get(Run, run_id).state == "running"


def test_normal_restart_of_waiting_limit_keeps_same_logical_run(tmp_path):
    engine = make_engine(tmp_path)
    run_id, _ = seed(engine, groups=2, account_count=1)
    settings = SettingsService(engine)
    service = RunService(engine, settings)
    service.start()
    with Session(engine) as session:
        session.get(Run, run_id).state = "waiting_limit"
        session.commit()

    restarted = service.start()

    assert restarted["run_id"] == run_id
    assert restarted["state"] in {"running", "waiting_limit"}
    with Session(engine) as session:
        assert session.scalar(select(Run.id).order_by(Run.id.desc()).limit(1)) == run_id


def test_ignore_limits_resets_only_participating_enabled_accounts(tmp_path):
    engine = make_engine(tmp_path)
    run_id, active_ids = seed(engine, groups=1, account_count=2)
    settings = SettingsService(engine)
    settings.update({"max_groups_per_account": 7})
    start = datetime(2026, 8, 26, 8, 0, 0)
    with Session(engine) as session:
        disabled = Account(vk_user_id=999, enabled=False, auth_status="ok")
        session.add(disabled)
        session.flush()
        disabled_id = disabled.id
        for account_id in [*active_ids, disabled_id]:
            session.add(AccountQuota(
                account_id=account_id,
                window_started_at=start,
                window_ends_at=start + timedelta(hours=24),
                consumed=7,
            ))
        session.commit()

    started = RunService(engine, settings).start(ignore_limits=True)

    assert started["run_id"] == run_id
    with Session(engine) as session:
        for account_id in active_ids:
            assert session.get(AccountQuota, account_id) is None
        assert session.get(AccountQuota, disabled_id).consumed == 7
    assert settings.all()["max_groups_per_account"] == 7
