from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_v049_desktop_webview_never_auto_opens_debug_tools():
    desktop = (ROOT / "desktop" / "main.py").read_text(encoding="utf-8")
    assert "webview.start(" in desktop
    assert "debug=False" in desktop
    assert "debug=True" not in desktop


def test_v049_viewport_override_is_loaded_after_legacy_layout_css():
    main = (ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
    global_index = main.index("./styles/global.css")
    v041_index = main.index("./styles/v041.css")
    v049_index = main.index("./styles/v049.css")
    assert global_index < v041_index < v049_index

    css = (ROOT / "frontend" / "src" / "styles" / "v049.css").read_text(encoding="utf-8")
    assert "position: fixed" in css
    assert "inset: 0" in css
    assert "height: 100% !important" in css
    assert "overflow: auto !important" in css
    assert "100vh" not in css
