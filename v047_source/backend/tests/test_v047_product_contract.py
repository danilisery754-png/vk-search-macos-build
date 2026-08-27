from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.time import api_timestamp, utc_from_unix
from app.db.base import Base
from app.db.models import Account, Dialog, DialogFolder
from app.services.inbox import InboxService


def make_engine(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'product-v047.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return engine


class FakeAccounts:
    pass


def test_dialog_folders_are_account_scoped_and_filter_dialogs(tmp_path):
    engine = make_engine(tmp_path)
    with Session(engine) as session:
        a1 = Account(vk_user_id=101, first_name="A", enabled=True, auth_status="ok")
        a2 = Account(vk_user_id=102, first_name="B", enabled=True, auth_status="ok")
        session.add_all([a1, a2])
        session.flush()
        d1 = Dialog(account_id=a1.id, peer_id=-1, title="Первый")
        d2 = Dialog(account_id=a1.id, peer_id=-2, title="Второй")
        d3 = Dialog(account_id=a2.id, peer_id=-3, title="Чужой")
        session.add_all([d1, d2, d3])
        session.commit()
        ids = (a1.id, a2.id, d1.id, d2.id, d3.id)

    service = InboxService(engine, FakeAccounts())
    folder = service.create_folder(ids[0], "Важные")
    assert folder["account_id"] == ids[0]
    service.set_dialog_folder(folder["id"], ids[2], True)
    rows = service.list_dialogs(account_id=ids[0], folder_id=folder["id"])
    assert [row["id"] for row in rows] == [ids[2]]
    assert folder["id"] in rows[0]["folder_ids"]

    try:
        service.set_dialog_folder(folder["id"], ids[4], True)
    except ValueError as exc:
        assert "аккаунт" in str(exc).lower()
    else:
        raise AssertionError("cross-account folder membership must be rejected")

    folders = service.list_folders(account_id=ids[0])
    assert folders == [{"id": folder["id"], "account_id": ids[0], "name": "Важные", "dialogs_count": 1}]


def test_api_timestamps_are_explicit_utc_and_unix_is_utc():
    value = datetime(2026, 8, 27, 10, 20, 30)
    assert api_timestamp(value) == "2026-08-27T10:20:30+00:00"
    assert utc_from_unix(0) == datetime(1970, 1, 1, 0, 0, 0)


def test_user_visible_frontend_contract_is_v048():
    root = Path(__file__).resolve().parents[2]
    inbox = (root / "frontend/src/pages/InboxPage.tsx").read_text(encoding="utf-8")
    dashboard = (root / "frontend/src/pages/DashboardPage.tsx").read_text(encoding="utf-8")
    settings = (root / "frontend/src/pages/SettingsPage.tsx").read_text(encoding="utf-8")
    groups = (root / "frontend/src/pages/GroupsPage.tsx").read_text(encoding="utf-8")
    shell = (root / "frontend/src/components/Shell.tsx").read_text(encoding="utf-8")
    css = (root / "frontend/src/styles/global.css").read_text(encoding="utf-8")

    assert "Прочитанные" not in inbox
    assert "Папки" in inbox and "/inbox/folders" in inbox
    assert "Как начать" not in dashboard
    assert "Минимум временных повторов" in settings
    assert "Масштаб интерфейса" in settings
    assert "interface_compact" not in settings
    assert "Выбрано:" in groups
    assert "VK Search" in shell
    assert "max-width: 1700px" not in css


def test_every_frontend_timestamp_uses_system_timezone_helper():
    root = Path(__file__).resolve().parents[2] / "frontend/src"
    offenders: list[str] = []
    for path in list((root / "pages").glob("*.tsx")) + list((root / "components").glob("*.tsx")):
        text = path.read_text(encoding="utf-8")
        if "new Date(" in text or ".toLocaleString(" in text or ".toLocaleTimeString(" in text or ".toLocaleDateString(" in text:
            offenders.append(path.name)
    assert offenders == [], f"timestamps bypass system-time helper: {offenders}"


def test_user_visible_branding_and_release_contract():
    root = Path(__file__).resolve().parents[2]
    main = (root / "backend/app/main.py").read_text(encoding="utf-8")
    spec = (root / "build/VKOutreachManagerMac.spec").read_text(encoding="utf-8")
    build = (root / "build/BUILD_MACOS.sh").read_text(encoding="utf-8")
    assert 'title="VK Search"' in main
    assert 'version="0.4.9"' in main
    assert 'name="VK Search.app"' in spec
    assert 'CFBundleDisplayName": "VK Search"' in spec
    assert "VK_Search_0.4.9_macOS_arm64.dmg" in build
