from __future__ import annotations

from app.core.config import AppConfig
from app.main import create_app


def test_v049_archive_routes_live_under_api_prefix(tmp_path):
    app = create_app(AppConfig(data_dir=tmp_path, frontend_dir=tmp_path / "frontend"))
    paths = {route.path for route in app.routes}

    assert "/api/inbox/archive" in paths
    assert "/api/inbox/dialogs/{dialog_id}/archive" in paths
    assert "/api/inbox/dialogs/{dialog_id}/restore" in paths
    assert "/inbox/archive" not in paths
