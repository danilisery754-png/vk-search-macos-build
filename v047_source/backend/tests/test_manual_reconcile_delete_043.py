from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import AppConfig
from app.core.enums import WorkItemState
from app.db.models import Community, EventLog, Run, WorkItem
from app.main import create_app


def _seed_item(session, run_id, community_id, state, *, started=False):
    item = WorkItem(
        run_id=run_id, community_id=community_id, state=state,
        started_at=datetime.utcnow() if started else None,
        quota_counted_at=datetime.utcnow() if started else None,
    )
    session.add(item)
    session.flush()
    return item.id


def test_manual_remove_allows_reconcile_but_not_processing(tmp_path):
    app = create_app(AppConfig(data_dir=tmp_path, frontend_dir=tmp_path / "frontend"))
    with TestClient(app) as client:
        with Session(app.state.services.engine) as session:
            run = Run(state="running")
            community = Community(vk_id=123, screen_name="club123", name="Test", canonical_url="https://vk.com/club123")
            session.add_all([run, community])
            session.flush()
            waiting_id = _seed_item(session, run.id, community.id, WorkItemState.WAITING)
            session.flush()
            community2 = Community(vk_id=124, screen_name="club124", name="Check", canonical_url="https://vk.com/club124")
            community3 = Community(vk_id=125, screen_name="club125", name="Processing", canonical_url="https://vk.com/club125")
            session.add_all([community2, community3])
            session.flush()
            reconcile_id = _seed_item(session, run.id, community2.id, WorkItemState.RECONCILE_REQUIRED, started=True)
            processing_id = _seed_item(session, run.id, community3.id, WorkItemState.PROCESSING, started=True)
            session.commit()

        response = client.post("/api/groups/remove", json={"ids": [waiting_id, reconcile_id, processing_id]})
        assert response.status_code == 200
        assert response.json()["removed"] == 2

        with Session(app.state.services.engine) as session:
            assert session.get(WorkItem, waiting_id) is None
            assert session.get(WorkItem, reconcile_id) is None
            assert session.get(WorkItem, processing_id) is not None


def test_dashboard_event_time_is_explicit_utc(tmp_path):
    app = create_app(AppConfig(data_dir=tmp_path, frontend_dir=tmp_path / "frontend"))
    with TestClient(app) as client:
        with Session(app.state.services.engine) as session:
            session.add(EventLog(created_at=datetime(2026, 8, 26, 7, 54, 40), user_message="test", level="info"))
            session.commit()
        payload = client.get("/api/dashboard").json()
        assert payload["events"][0]["time"].endswith("+00:00")
