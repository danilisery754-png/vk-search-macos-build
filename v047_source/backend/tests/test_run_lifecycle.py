from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.enums import WorkItemState
from app.db.base import Base
from app.db.models import Account, Community, Run, WorkItem
from app.services.runs import RunService
from app.services.settings import SettingsService


def test_stopped_run_can_be_started_again_without_losing_groups(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'runs.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(vk_user_id=101, auth_status="ok", enabled=True)
        community = Community(vk_id=501, canonical_url="https://vk.com/club501")
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
        run_id, item_id = run.id, item.id

    service = RunService(engine, SettingsService(engine))
    assert service.stop()["state"] == "stopped"
    restarted = service.start()

    assert restarted["run_id"] == run_id
    assert restarted["state"] == "running"
    with Session(engine) as session:
        item = session.get(WorkItem, item_id)
        # v0.4.1 deliberately returns not-started work to the durable shared
        # pool. The next eligible account claims it transactionally.
        assert item.state == WorkItemState.WAITING
        assert item.assigned_account_id is None


def test_stopped_work_of_disabled_account_returns_to_shared_pool(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'runs.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        disabled = Account(vk_user_id=101, auth_status="ok", enabled=False)
        enabled = Account(vk_user_id=102, auth_status="ok", enabled=True)
        community = Community(vk_id=501, canonical_url="https://vk.com/club501")
        run = Run(state="stopped")
        session.add_all([disabled, enabled, community, run])
        session.flush()
        item = WorkItem(
            run_id=run.id,
            community_id=community.id,
            assigned_account_id=disabled.id,
            state=WorkItemState.PAUSED,
        )
        session.add(item)
        session.commit()
        item_id = item.id

    restarted = RunService(engine, SettingsService(engine)).start()

    assert restarted["assigned"] == 0
    with Session(engine) as session:
        item = session.scalar(select(WorkItem).where(WorkItem.id == item_id))
        assert item.state == WorkItemState.WAITING
        assert item.assigned_account_id is None


def test_start_snapshots_original_group_count_once(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'runs-original-count.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(vk_user_id=303, auth_status="ok", enabled=True)
        run = Run(state="draft")
        session.add_all([account, run])
        session.flush()
        for vk_id in (601, 602, 603):
            community = Community(vk_id=vk_id, canonical_url=f"https://vk.com/club{vk_id}")
            session.add(community)
            session.flush()
            session.add(WorkItem(run_id=run.id, community_id=community.id, state=WorkItemState.WAITING))
        session.commit()
        run_id = run.id

    service = RunService(engine, SettingsService(engine))
    service.start()
    with Session(engine) as session:
        run = session.get(Run, run_id)
        assert run.original_count == 3
        one = session.scalar(select(WorkItem).where(WorkItem.run_id == run_id).limit(1))
        session.delete(one)
        run.state = "stopped"
        session.commit()

    service.start()
    with Session(engine) as session:
        assert session.get(Run, run_id).original_count == 3
