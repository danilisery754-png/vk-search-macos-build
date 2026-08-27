from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import AppConfig
from app.core.enums import WorkItemState
from app.db.models import Account, AccountQuota, Community, Run, WorkItem
from app.main import create_app


def make_app(tmp_path):
    return create_app(AppConfig(data_dir=tmp_path, frontend_dir=tmp_path / "frontend"))


def seed_account(session: Session, *, vk_user_id: int = 1001) -> Account:
    account = Account(vk_user_id=vk_user_id, first_name="Quota", enabled=True, auth_status="ok")
    session.add(account)
    session.flush()
    return account


def seed_waiting_run(session: Session, *, vk_id: int = 5001) -> tuple[Run, WorkItem]:
    run = Run(state="draft")
    community = Community(vk_id=vk_id, canonical_url=f"https://vk.com/club{vk_id}")
    session.add_all([run, community])
    session.flush()
    item = WorkItem(run_id=run.id, community_id=community.id, state=WorkItemState.WAITING)
    session.add(item)
    session.flush()
    return run, item


def test_accounts_api_exposes_persisted_daily_quota_snapshot(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        services = app.state.services
        services.settings.update({"max_groups_per_account": 5})
        now = datetime.utcnow()
        with Session(services.engine) as session:
            account = seed_account(session)
            session.add(AccountQuota(
                account_id=account.id,
                window_started_at=now,
                window_ends_at=now + timedelta(hours=24),
                consumed=3,
            ))
            session.commit()
            account_id = account.id
            window_end = now + timedelta(hours=24)

        response = client.get("/api/accounts")

    assert response.status_code == 200
    row = next(item for item in response.json() if item["id"] == account_id)
    assert row["daily_limit"] == 5
    assert row["quota_consumed"] == 3
    assert row["quota_available"] == 2
    assert datetime.fromisoformat(row["quota_window_ends_at"]) == window_end


def test_normal_start_respects_existing_quota_and_explicit_override_resets_it(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        services = app.state.services
        services.settings.update({"max_groups_per_account": 7})
        now = datetime.utcnow()
        with Session(services.engine) as session:
            account = seed_account(session)
            run, _ = seed_waiting_run(session)
            session.add(AccountQuota(
                account_id=account.id,
                window_started_at=now,
                window_ends_at=now + timedelta(hours=24),
                consumed=4,
            ))
            session.commit()
            account_id = account.id
            run_id = run.id

        normal = client.post("/api/work/start", json={"mode": "respect_limits"})
        with Session(services.engine) as session:
            after_normal = session.get(AccountQuota, account_id).consumed
            session.get(Run, run_id).state = "stopped"
            session.commit()

        override = client.post(
            "/api/work/start",
            json={"mode": "reset_limits_for_participating_accounts"},
        )
        after_override = services.runs.quota.snapshot(account_id)

    assert normal.status_code == 200
    assert after_normal == 4
    assert override.status_code == 200
    assert override.json()["quota_reset"] is True
    assert after_override.consumed == 0
    assert after_override.available == 7
    assert after_override.window_started_at is None
    assert services.settings.all()["max_groups_per_account"] == 7


def test_import_replace_waiting_preserves_started_work_and_replaces_only_tail(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        services = app.state.services
        with Session(services.engine) as session:
            run = Run(state="running")
            old_waiting = Community(vk_id=7001, canonical_url="https://vk.com/club7001")
            started_group = Community(vk_id=7002, canonical_url="https://vk.com/club7002")
            session.add_all([run, old_waiting, started_group])
            session.flush()
            session.add_all([
                WorkItem(run_id=run.id, community_id=old_waiting.id, state=WorkItemState.WAITING),
                WorkItem(
                    run_id=run.id,
                    community_id=started_group.id,
                    state=WorkItemState.PROCESSING,
                    started_at=datetime.utcnow(),
                ),
            ])
            session.commit()
            run_id = run.id

        response = client.post(
            "/api/groups/import",
            json={"text": "https://vk.com/club7003", "mode": "replace_waiting"},
        )

        with Session(services.engine) as session:
            vk_ids = {
                session.get(Community, item.community_id).vk_id
                for item in session.scalars(select(WorkItem).where(WorkItem.run_id == run_id)).all()
            }

    assert response.status_code == 200
    assert response.json()["replaced"] == 1
    assert vk_ids == {7002, 7003}


def test_import_cancel_is_a_noop(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        services = app.state.services
        with Session(services.engine) as session:
            run, _ = seed_waiting_run(session, vk_id=8101)
            session.commit()
            run_id = run.id

        before = client.get("/api/groups").json()["total"]
        response = client.post(
            "/api/groups/import",
            json={"text": "https://vk.com/club8102", "mode": "cancel"},
        )
        after = client.get("/api/groups").json()["total"]
        with Session(services.engine) as session:
            count = session.scalar(
                select(func.count()).select_from(WorkItem).where(WorkItem.run_id == run_id)
            )

    assert response.status_code == 200
    assert response.json()["cancelled"] is True
    assert before == after == count == 1
