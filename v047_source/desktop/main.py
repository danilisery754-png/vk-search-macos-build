from __future__ import annotations

import ctypes
import asyncio
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import socket
from pathlib import Path


APP_TITLE = "VK Search"
MUTEX_NAME = "Local\\VKOutreachManager.SingleInstance"


def project_root() -> Path:
    frozen = getattr(sys, "_MEIPASS", None)
    return Path(frozen) if frozen else Path(__file__).resolve().parents[1]


def configure_runtime() -> None:
    root = project_root()
    app_resources = Path(sys.executable).resolve().parent.parent / "Resources"
    browser_candidates = (
        app_resources / "playwright-browsers",
        root / "playwright-browsers",
        root / "build" / "playwright-browsers",
        root / ".playwright-browsers",
    )
    browsers = next((candidate for candidate in browser_candidates if candidate.exists()), None)
    if browsers is not None:
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers))
    os.environ.setdefault("VK_OUTREACH_FRONTEND_DIR", str(root / "frontend" / "dist"))


def acquire_single_instance():
    if os.name != "nt":
        return None
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle or kernel32.GetLastError() == 183:
        return False
    return handle


def ensure_webview_runtime(data_dir: Path) -> None:
    if os.name != "nt":
        return
    marker = data_dir / "webview-runtime-checked-v044"
    if marker.exists():
        return
    candidates = [
        Path(sys.executable).resolve().parent / "MicrosoftEdgeWebView2Setup.exe",
        project_root() / "MicrosoftEdgeWebView2Setup.exe",
        project_root() / "build" / "MicrosoftEdgeWebView2Setup.exe",
    ]
    installer = next((candidate for candidate in candidates if candidate.exists()), None)
    if installer is None:
        return
    try:
        result = subprocess.run(
            [str(installer), "/silent", "/install"],
            check=False,
            timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return
    if result.returncode not in {0, 3010}:
        return
    data_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text("ok", encoding="utf-8")


def wait_until_ready(url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=1) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(0.15)
    raise RuntimeError(f"Локальное ядро не запустилось: {last_error}")


def find_available_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


def is_self_test(argv: list[str] | None = None) -> bool:
    return "--self-test" in (argv if argv is not None else sys.argv)


def is_browser_self_test(argv: list[str] | None = None) -> bool:
    return "--browser-self-test" in (argv if argv is not None else sys.argv)


def is_frontend_self_test(argv: list[str] | None = None) -> bool:
    return "--frontend-self-test" in (argv if argv is not None else sys.argv)


def write_self_test_failure() -> None:
    log_value = os.environ.get("VK_OUTREACH_SELF_TEST_LOG", "").strip()
    if not log_value:
        return
    log_path = Path(log_value)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(traceback.format_exc(), encoding="utf-8")


def create_local_server(application, host: str, port: int, log_level: str):
    import uvicorn

    return uvicorn.Server(uvicorn.Config(
        application,
        host=host,
        port=port,
        log_level=log_level,
        access_log=False,
        log_config=None,
    ))


def run_self_test() -> int:
    from app.core.config import AppConfig
    from app.main import create_app

    with tempfile.TemporaryDirectory(prefix="vk-search-self-test-") as temporary:
        config = AppConfig(data_dir=Path(temporary), port=find_available_port("127.0.0.1"))
        address = f"http://{config.host}:{config.port}"
        server = create_local_server(create_app(config), config.host, config.port, "error")
        thread = threading.Thread(target=server.run, name="vk-search-self-test", daemon=True)
        thread.start()
        try:
            wait_until_ready(address, timeout=30)
            with urllib.request.urlopen(address, timeout=3) as response:
                if response.status != 200:
                    raise RuntimeError(f"Интерфейс вернул HTTP {response.status}")
        finally:
            server.should_exit = True
            thread.join(timeout=10)
        if thread.is_alive():
            raise RuntimeError("Локальное ядро не завершилось после self-test")
    return 0


def run_browser_self_test() -> int:
    async def verify_browser() -> None:
        from playwright.async_api import async_playwright

        with tempfile.TemporaryDirectory(prefix="vk-search-browser-self-test-") as temporary:
            async with async_playwright() as playwright:
                context = await playwright.chromium.launch_persistent_context(
                    user_data_dir=str(Path(temporary) / "profile"),
                    headless=True,
                )
                try:
                    page = context.pages[0] if context.pages else await context.new_page()
                    await page.set_content(
                        "<!doctype html><html><head><title>VK Search Browser OK</title></head>"
                        "<body><main id='result'>browser-ready</main></body></html>"
                    )
                    if await page.title() != "VK Search Browser OK":
                        raise RuntimeError("Встроенный Chromium вернул неверный заголовок")
                    if await page.locator("#result").text_content() != "browser-ready":
                        raise RuntimeError("Встроенный Chromium не отрисовал тестовую страницу")
                finally:
                    await context.close()

    asyncio.run(verify_browser())
    return 0


def run_frontend_self_test() -> int:
    from app.core.config import AppConfig
    from app.main import create_app
    from portability import run_frontend_probe, verify_frontend_assets, wait_for_health

    with tempfile.TemporaryDirectory(prefix="vk-search-frontend-self-test-") as temporary:
        config = AppConfig(data_dir=Path(temporary), port=find_available_port("127.0.0.1"))
        address = f"http://{config.host}:{config.port}"
        server = create_local_server(create_app(config), config.host, config.port, "error")
        thread = threading.Thread(target=server.run, name="vk-search-frontend-self-test", daemon=True)
        thread.start()
        try:
            wait_for_health(address, timeout_seconds=30)
            verify_frontend_assets(address, timeout_seconds=8)
            result = run_frontend_probe(address)
            if result.get("ok") is not True:
                raise RuntimeError("Production frontend probe не подтвердил запуск интерфейса")
        finally:
            server.should_exit = True
            thread.join(timeout=10)
        if thread.is_alive():
            raise RuntimeError("Локальное ядро не завершилось после frontend self-test")
    return 0


def desktop_gui(platform_name: str | None = None) -> str:
    return "cocoa" if (platform_name or sys.platform) == "darwin" else "edgechromium"


def desktop_tray_enabled(platform_name: str | None = None) -> bool:
    return (platform_name or sys.platform) != "darwin"


def main() -> int:
    configure_runtime()
    if is_frontend_self_test():
        try:
            return run_frontend_self_test()
        except Exception:
            write_self_test_failure()
            return 1
    if is_browser_self_test():
        try:
            return run_browser_self_test()
        except Exception:
            write_self_test_failure()
            return 1
    if is_self_test():
        try:
            return run_self_test()
        except Exception:
            write_self_test_failure()
            return 1
    mutex = acquire_single_instance()
    if mutex is False:
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None, "Приложение уже запущено.", APP_TITLE, 0x40)
        return 0

    import webview
    from app.core.config import AppConfig
    from app.main import create_app
    from portability import open_browser_fallback, verify_frontend_assets, wait_for_health, wait_for_ui_ready

    config = AppConfig()
    ensure_webview_runtime(config.data_dir)
    address = f"http://{config.host}:{config.port}"
    server = create_local_server(create_app(config), config.host, config.port, "warning")
    server_thread = threading.Thread(target=server.run, name="vk-search-core", daemon=True)
    server_thread.start()
    try:
        wait_for_health(address, timeout_seconds=30)
        verify_frontend_assets(address, timeout_seconds=8)
    except Exception as exc:
        server.should_exit = True
        server_thread.join(timeout=10)
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None, str(exc), APP_TITLE, 0x10)
        return 1

    window = webview.create_window(
        APP_TITLE,
        address,
        width=1440,
        height=900,
        min_size=(1100, 700),
        background_color="#09101d",
        text_select=True,
    )

    tray_stop = threading.Event()

    def start_tray():
        try:
            import pystray
            from PIL import Image

            icon_path = project_root() / "build" / "app-icon.png"
            image = Image.open(icon_path) if icon_path.exists() else Image.new("RGBA", (64, 64), "#347df4")

            def show(_icon=None, _item=None):
                window.restore()
                window.show()

            def quit_app(icon, _item=None):
                tray_stop.set()
                icon.stop()
                window.destroy()

            icon = pystray.Icon("vk-search", image, APP_TITLE, pystray.Menu(
                pystray.MenuItem("Открыть", show, default=True),
                pystray.MenuItem("Выйти", quit_app),
            ))
            icon.run()
        except Exception:
            return

    if desktop_tray_enabled():
        tray_thread = threading.Thread(target=start_tray, name="vk-search-tray", daemon=True)
        tray_thread.start()

    def verify_desktop_ui() -> None:
        if wait_for_ui_ready(window, timeout_seconds=10.0):
            return
        opened = open_browser_fallback(address)
        if opened and os.name == "nt":
            ctypes.windll.user32.MessageBoxW(
                None,
                "Встроенный интерфейс не отрисовался. Интерфейс открыт в браузере по локальному адресу.",
                APP_TITLE,
                0x30,
            )

    try:
        webview.start(verify_desktop_ui, gui=desktop_gui(), debug=False, private_mode=False)
    finally:
        tray_stop.set()
        server.should_exit = True
        server_thread.join(timeout=10)
        if os.name == "nt" and mutex:
            ctypes.windll.kernel32.CloseHandle(mutex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
