from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all("playwright")
webview_datas, webview_binaries, webview_hiddenimports = collect_all("webview")

datas = [
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(ROOT / "backend" / "alembic"), "alembic"),
    (str(ROOT / "backend" / "alembic.ini"), "."),
    # Playwright browsers are staged intact after PyInstaller creates the app bundle.
] + playwright_datas + webview_datas

binaries = playwright_binaries + webview_binaries
hiddenimports = sorted(set(
    playwright_hiddenimports
    + webview_hiddenimports
    + collect_submodules("app")
    + collect_submodules("uvicorn")
))

a = Analysis(
    [str(ROOT / "desktop" / "main.py")],
    pathex=[str(ROOT / "backend"), str(ROOT / "desktop")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VK Search",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VK Search",
)

app = BUNDLE(
    coll,
    name="VK Search.app",
    icon=str(ROOT / "build" / "app-icon.icns"),
    bundle_identifier="com.vkoutreach.manager",
    version="0.4.9",
    info_plist={
        "CFBundleDisplayName": "VK Search",
        "CFBundleShortVersionString": "0.4.9",
        "CFBundleVersion": "0.4.9",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "NSSupportsAutomaticGraphicsSwitching": True,
    },
)
