import importlib.util
import json
import sys
from pathlib import Path

import pytest


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_desktop_main():
    path = project_root() / "desktop" / "main.py"
    spec = importlib.util.spec_from_file_location("desktop_main_v044", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_portability():
    path = project_root() / "desktop" / "portability.py"
    assert path.exists(), "desktop/portability.py must provide production frontend preflight"
    spec = importlib.util.spec_from_file_location("desktop_portability_v044", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


def test_frontend_self_test_flag_is_detected_explicitly():
    desktop = load_desktop_main()

    assert desktop.is_frontend_self_test(["program.exe", "--frontend-self-test"]) is True
    assert desktop.is_frontend_self_test(["program.exe"]) is False


def test_frontend_self_test_is_dispatched_before_gui(monkeypatch):
    desktop = load_desktop_main()
    monkeypatch.setattr(sys, "argv", ["program.exe", "--frontend-self-test"])
    monkeypatch.setattr(desktop, "run_frontend_self_test", lambda: 29)

    assert desktop.main() == 29


def test_wait_for_health_requires_ok_json(monkeypatch):
    portability = load_portability()
    calls = []

    def fake_open(url, timeout):
        calls.append((url, timeout))
        return FakeResponse(json.dumps({"ok": True, "version": "0.4.4"}).encode())

    monkeypatch.setattr(portability, "urlopen", fake_open)
    payload = portability.wait_for_health("http://127.0.0.1:43210", timeout_seconds=0.5)

    assert payload["ok"] is True
    assert calls[0][0] == "http://127.0.0.1:43210/api/health"


def test_verify_frontend_assets_fetches_only_local_production_assets(monkeypatch):
    portability = load_portability()
    requested = []
    index = b"<!doctype html><html><head><link rel='stylesheet' href='/assets/app.css'></head><body><div id='root'></div><script type='module' src='/assets/app.js'></script></body></html>"
    bodies = {
        "http://127.0.0.1:43210/": index,
        "http://127.0.0.1:43210/assets/app.css": b"body{}",
        "http://127.0.0.1:43210/assets/app.js": b"console.log('ok')",
    }

    def fake_open(url, timeout):
        requested.append(url)
        return FakeResponse(bodies[url])

    monkeypatch.setattr(portability, "urlopen", fake_open)
    assets = portability.verify_frontend_assets("http://127.0.0.1:43210", timeout_seconds=0.5)

    assert assets == ["/assets/app.css", "/assets/app.js"]
    assert requested == [
        "http://127.0.0.1:43210/",
        "http://127.0.0.1:43210/assets/app.css",
        "http://127.0.0.1:43210/assets/app.js",
    ]


def test_verify_frontend_assets_rejects_dev_or_external_entry(monkeypatch):
    portability = load_portability()

    for index in (
        b'<script type="module" src="/src/main.tsx"></script>',
        b'<script src="https://cdn.example.com/app.js"></script>',
    ):
        monkeypatch.setattr(portability, "urlopen", lambda url, timeout, body=index: FakeResponse(body))
        with pytest.raises(RuntimeError):
            portability.verify_frontend_assets("http://127.0.0.1:43210", timeout_seconds=0.5)


def test_frontend_build_targets_conservative_windows_browser_baseline():
    root = project_root()
    vite = (root / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    index = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    main_tsx = (root / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")

    assert "chrome109" in vite and "edge109" in vite
    assert "target: 'es2022'" not in vite
    assert "vk-ui-bootstrap-failure" in index
    assert "__VK_UI_BOOTED__" in index
    assert "UiReadyReporter" in main_tsx


def test_frontend_does_not_require_google_fonts():
    css = (project_root() / "frontend" / "src" / "styles" / "global.css").read_text(encoding="utf-8")
    assert "fonts.googleapis.com" not in css
    assert "fonts.gstatic.com" not in css
    assert '"Segoe UI"' in css


def test_desktop_has_ui_readiness_and_one_shot_browser_fallback():
    portability = load_portability()
    assert hasattr(portability, "wait_for_ui_ready")
    assert hasattr(portability, "open_browser_fallback")
    desktop = (project_root() / "desktop" / "main.py").read_text(encoding="utf-8")
    assert "wait_for_ui_ready" in desktop
    assert "open_browser_fallback" in desktop
    assert "verify_frontend_assets" in desktop


def test_frontend_self_test_runs_real_react_probe():
    desktop = (project_root() / "desktop" / "main.py").read_text(encoding="utf-8")
    assert "run_frontend_probe" in desktop
    assert "--frontend-self-test" in desktop


def test_spa_index_is_never_cached_across_upgrades():
    backend_main = (project_root() / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert '"Cache-Control": "no-store"' in backend_main


def test_installer_repairs_webview2_before_launching_app():
    installer = (project_root() / "build" / "installer.iss").read_text(encoding="utf-8")
    run_section = installer.split("[Run]", 1)[1]
    webview_line = 'Filename: "{app}\\MicrosoftEdgeWebView2Setup.exe"'
    app_line = 'Filename: "{app}\\{#MyAppExeName}"'
    assert webview_line in run_section
    assert '/silent /install' in run_section
    assert 'waituntilterminated' in run_section
    assert run_section.index(webview_line) < run_section.index(app_line)


def test_windows_build_runs_production_frontend_self_test_twice():
    build = (project_root() / "build" / "BUILD_WINDOWS.ps1").read_text(encoding="utf-8")
    assert '--frontend-self-test' in build
    assert 'frontend-self-test' in build
    assert 'MicrosoftEdgeWebView2Setup.exe' in build


def test_all_release_metadata_is_v044():
    root = project_root()
    assert 'version = "0.4.4"' in (root / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version="0.4.4"' in (root / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert '"version": "0.4.4"' in (root / "backend" / "app" / "api" / "routes.py").read_text(encoding="utf-8")
    assert '"version": "0.4.4"' in (root / "frontend" / "package.json").read_text(encoding="utf-8")
    installer = (root / "build" / "installer.iss").read_text(encoding="utf-8")
    assert 'MyAppVersion "0.4.4"' in installer
    assert 'VK_Outreach_Manager_Setup_0.4.4' in installer

