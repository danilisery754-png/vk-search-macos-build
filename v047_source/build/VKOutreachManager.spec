from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPEC).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend" / "dist"
BROWSERS = ROOT / "build" / "playwright-browsers"

datas = [
    (str(FRONTEND), "frontend/dist"),
    (str(ROOT / "build" / "app-icon.png"), "build"),
    (str(BACKEND / "alembic.ini"), "."),
    (str(BACKEND / "alembic"), "alembic"),
]
if BROWSERS.exists():
    datas.append((str(BROWSERS), "playwright-browsers"))
pw_datas, pw_binaries, pw_hidden = collect_all("playwright")
webview_datas, webview_binaries, webview_hidden = collect_all("webview")
datas += pw_datas + webview_datas
binaries = pw_binaries + webview_binaries
hiddenimports = pw_hidden + webview_hidden + collect_submodules("app") + ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto"]

a = Analysis(
    [str(ROOT / "desktop" / "main.py")],
    pathex=[str(BACKEND), str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="VK Outreach Manager", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, console=False,
    icon=str(ROOT / "build" / "app-icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, name="VK Outreach Manager")
