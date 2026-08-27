from __future__ import annotations

import asyncio
import base64
from pathlib import Path

from fastapi.responses import FileResponse

from app.core.config import AppConfig
from app.main import create_app


ROOT = Path(__file__).resolve().parents[2]


def test_sidebar_icon_route_serves_real_packaged_file(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    icon = frontend / "vk-search-icon.jpg"
    icon.write_bytes(b"\xff\xd8fake-jpeg\xff\xd9")

    app = create_app(AppConfig(data_dir=tmp_path / "data-dir", frontend_dir=frontend))
    route = next(route for route in app.routes if getattr(route, "path", None) == "/vk-search-icon.jpg")
    response = asyncio.run(route.endpoint())

    assert isinstance(response, FileResponse)
    assert Path(response.path) == icon
    assert response.media_type == "image/jpeg"


def test_sidebar_avatar_is_byte_identical_to_packaged_application_icon_source():
    sidebar = (ROOT / "frontend" / "public" / "vk-search-icon.jpg").read_bytes()
    packaged = base64.b64decode(
        (ROOT / "build" / "vk-search-icon.jpg.b64").read_text(encoding="utf-8").strip(),
        validate=True,
    )

    assert sidebar.startswith(b"\xff\xd8")
    assert len(sidebar) > 10_000
    assert sidebar == packaged
