from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import secrets
from app.core.config import APP_NAME, default_data_dir


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_desktop_main():
    path = project_root() / "desktop" / "main.py"
    spec = importlib.util.spec_from_file_location("desktop_main_macos", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_darwin_data_dir_uses_application_support(monkeypatch, tmp_path):
    monkeypatch.delenv("VK_OUTREACH_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    assert default_data_dir() == tmp_path / "Library" / "Application Support" / APP_NAME


def test_macos_keychain_key_is_created_once_and_reused(monkeypatch, tmp_path):
    stored = {"key": None}
    add_calls = []

    def fake_run(command, **kwargs):
        if command[1] == "find-generic-password":
            if stored["key"] is None:
                return subprocess.CompletedProcess(command, 44, "", "not found")
            return subprocess.CompletedProcess(command, 0, stored["key"] + "\n", "")
        if command[1] == "add-generic-password":
            stored["key"] = command[command.index("-w") + 1]
            add_calls.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(command)

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(secrets, "subprocess", SimpleNamespace(run=fake_run), raising=False)
    protector = secrets.DPAPIProtector(tmp_path / "legacy-development.key")

    encrypted = protector.protect("vk-token-secret")
    assert encrypted.startswith(b"keychain:")
    assert protector.unprotect(encrypted) == "vk-token-secret"
    assert len(add_calls) == 1
    assert not (tmp_path / "legacy-development.key").exists()


def test_macos_keychain_failure_does_not_leak_generated_key(monkeypatch, tmp_path):
    def failing_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 51, "", "keychain unavailable")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(secrets, "subprocess", SimpleNamespace(run=failing_run), raising=False)
    protector = secrets.DPAPIProtector(tmp_path / "legacy-development.key")

    with pytest.raises(secrets.SecretProtectionError) as error:
        protector.protect("must-not-leak")

    assert "Keychain" in str(error.value)
    assert "must-not-leak" not in str(error.value)


def test_darwin_selects_cocoa_and_disables_background_tray():
    desktop = load_desktop_main()

    gui = getattr(desktop, "desktop_gui", lambda _platform=None: None)("darwin")
    tray_enabled = getattr(desktop, "desktop_tray_enabled", lambda _platform=None: True)("darwin")

    assert gui == "cocoa"
    assert tray_enabled is False


def test_frozen_macos_runtime_finds_staged_playwright_browsers(monkeypatch, tmp_path):
    desktop = load_desktop_main()
    app_contents = tmp_path / "VK Outreach Manager.app" / "Contents"
    executable = app_contents / "MacOS" / "VK Outreach Manager"
    browsers = app_contents / "Resources" / "playwright-browsers"
    browsers.mkdir(parents=True)
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.touch()

    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "pyinstaller-meipass"), raising=False)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)

    desktop.configure_runtime()

    assert os.environ.get("PLAYWRIGHT_BROWSERS_PATH") == str(browsers)


def test_macos_release_build_contract_exists():
    root = project_root()
    build_script = root / "build" / "BUILD_MACOS.sh"
    spec_file = root / "build" / "VKOutreachManagerMac.spec"

    assert build_script.exists()
    assert spec_file.exists()

    build = build_script.read_text(encoding="utf-8")
    spec = spec_file.read_text(encoding="utf-8")

    assert "playwright install chromium" in build
    assert "--self-test" in build
    assert "--browser-self-test" in build
    assert "--frontend-self-test" in build
    assert "codesign --verify" in build
    assert "hdiutil verify" in build
    assert "VK_Outreach_Manager_0.4.5_macOS_arm64.dmg" in build
    assert "Contents/Resources/playwright-browsers" in build
    assert 'cp -R "$BROWSERS" "$APP_BROWSER_RESOURCES"' in build
    assert "com.vkoutreach.manager" in spec
    assert "target_arch=\"arm64\"" in spec
    assert "LSMinimumSystemVersion" in spec and "13.0" in spec
    assert 'ROOT / "build" / "playwright-browsers"' not in spec
    assert "frontend/dist" in spec
