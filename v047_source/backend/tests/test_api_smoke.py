import asyncio

from fastapi.testclient import TestClient

from app.core.config import AppConfig
from app.main import create_app
from app.services.accounts import AuthJob, BrowserJob


class LoopCheckingAccounts:
    """Fails if a job-start route is executed outside FastAPI's event loop."""

    def start_authorization(self, account_id=None):
        asyncio.get_running_loop()
        return AuthJob(id="auth-test", account_id=account_id)

    def start_open_messages(self, account_id):
        asyncio.get_running_loop()
        return BrowserJob(id="browser-test", account_id=account_id)


def test_health_dashboard_settings_and_empty_result_tables(tmp_path):
    config = AppConfig(data_dir=tmp_path, frontend_dir=tmp_path / "frontend")
    app = create_app(config)

    with TestClient(app) as client:
        health = client.get("/api/health")
        dashboard = client.get("/api/dashboard")
        settings = client.get("/api/settings")
        success = client.get("/api/results/success")
        failed = client.get("/api/results/failed")

    assert health.status_code == 200 and health.json()["ok"] is True
    assert dashboard.json()["metrics"]["remaining"] == 0
    assert settings.json()["max_groups_per_account"] == 50
    assert success.json() == {"total": 0, "items": []}
    assert failed.json() == {"total": 0, "items": []}


def test_settings_validation_is_in_russian(tmp_path):
    app = create_app(AppConfig(data_dir=tmp_path, frontend_dir=tmp_path / "frontend"))
    with TestClient(app) as client:
        response = client.patch("/api/settings", json={"values": {"max_groups_per_account": 0}})
    assert response.status_code == 422
    assert "Лимит" in response.json()["detail"]


def test_inbox_sync_interval_has_safe_bounds(tmp_path):
    app = create_app(AppConfig(data_dir=tmp_path, frontend_dir=tmp_path / "frontend"))
    with TestClient(app) as client:
        too_fast = client.patch("/api/settings", json={"values": {"inbox_sync_seconds": 1}})
        valid = client.patch("/api/settings", json={"values": {"inbox_sync_seconds": 30}})

    assert too_fast.status_code == 422
    assert "синхронизации" in too_fast.json()["detail"]
    assert valid.status_code == 200


def test_authorization_start_runs_on_the_application_event_loop(tmp_path):
    app = create_app(AppConfig(data_dir=tmp_path, frontend_dir=tmp_path / "frontend"))
    with TestClient(app) as client:
        app.state.services.accounts = LoopCheckingAccounts()
        response = client.post("/api/accounts/authorize")

    assert response.status_code == 202
    assert response.json()["id"] == "auth-test"


def test_open_messages_start_runs_on_the_application_event_loop(tmp_path):
    app = create_app(AppConfig(data_dir=tmp_path, frontend_dir=tmp_path / "frontend"))
    with TestClient(app) as client:
        app.state.services.accounts = LoopCheckingAccounts()
        response = client.post("/api/accounts/7/open-messages")

    assert response.status_code == 202
    assert response.json()["id"] == "browser-test"

class ConfirmCheckingAccounts:
    def confirm_authorization(self, job_id):
        assert job_id == "auth-test"
        return AuthJob(
            id=job_id,
            state="user_confirmed",
            message="Вход подтверждён, получаю токен VK",
        ).public()


def test_authorization_confirm_route_releases_waiting_login(tmp_path):
    app = create_app(AppConfig(data_dir=tmp_path, frontend_dir=tmp_path / "frontend"))
    with TestClient(app) as client:
        app.state.services.accounts = ConfirmCheckingAccounts()
        response = client.post("/api/accounts/authorize/auth-test/confirm")

    assert response.status_code == 200
    assert response.json()["state"] == "user_confirmed"
