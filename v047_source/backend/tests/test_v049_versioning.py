from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_v049_version_metadata_is_consistent():
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    pyproject = (ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    main = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    routes = (ROOT / "backend" / "app" / "api" / "routes.py").read_text(encoding="utf-8")
    mac_spec = (ROOT / "build" / "VKOutreachManagerMac.spec").read_text(encoding="utf-8")
    mac_build = (ROOT / "build" / "BUILD_MACOS.sh").read_text(encoding="utf-8")

    assert package["version"] == "0.4.9"
    assert 'version = "0.4.9"' in pyproject
    assert 'version="0.4.9"' in main
    assert '"version": "0.4.9"' in routes
    assert 'version="0.4.9"' in mac_spec
    assert '"CFBundleShortVersionString": "0.4.9"' in mac_spec
    assert '"CFBundleVersion": "0.4.9"' in mac_spec
    assert "VK_Search_0.4.9_macOS_arm64.dmg" in mac_build


def test_v049_keeps_existing_application_identity():
    mac_spec = (ROOT / "build" / "VKOutreachManagerMac.spec").read_text(encoding="utf-8")
    assert 'bundle_identifier="com.vkoutreach.manager"' in mac_spec
