from __future__ import annotations

import json
import threading
import time
import webbrowser
from html.parser import HTMLParser
from urllib.request import urlopen


class _FrontendAssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []
        self.script_count = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag.lower() == "script" and values.get("src"):
            self.script_count += 1
            self.assets.append(values["src"])
            return
        if tag.lower() == "link" and values.get("href"):
            rel = values.get("rel", "").lower().split()
            if "stylesheet" in rel:
                self.assets.append(values["href"])


def _read_200(url: str, timeout_seconds: float) -> bytes:
    with urlopen(url, timeout=timeout_seconds) as response:
        status = int(getattr(response, "status", 200))
        if status != 200:
            raise RuntimeError(f"HTTP {status}: {url}")
        return response.read()


def wait_for_health(base_url: str, timeout_seconds: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    health_url = f"{base_url.rstrip('/')}/api/health"
    while time.monotonic() < deadline:
        try:
            body = _read_200(health_url, min(1.5, max(timeout_seconds, 0.05)))
            payload = json.loads(body.decode("utf-8"))
            if isinstance(payload, dict) and payload.get("ok") is True:
                return payload
            last_error = RuntimeError("/api/health не вернул ok=true")
        except Exception as exc:
            last_error = exc
        time.sleep(0.05)
    detail = type(last_error).__name__ if last_error is not None else "unknown"
    raise RuntimeError(f"Локальное ядро не стало готово: {detail}")


def verify_frontend_assets(base_url: str, timeout_seconds: float = 8.0) -> list[str]:
    root_url = f"{base_url.rstrip('/')}/"
    index = _read_200(root_url, timeout_seconds).decode("utf-8", errors="replace")
    parser = _FrontendAssetParser()
    parser.feed(index)
    if parser.script_count < 1:
        raise RuntimeError("Production index.html не содержит JavaScript bundle")
    if not parser.assets:
        raise RuntimeError("Production index.html не содержит локальных assets")

    verified: list[str] = []
    for asset in parser.assets:
        if asset.startswith("http://") or asset.startswith("https://"):
            raise RuntimeError(f"Внешний обязательный frontend asset запрещён: {asset}")
        if asset.startswith("/src/") or not asset.startswith("/assets/"):
            raise RuntimeError(f"Найден не-production frontend asset: {asset}")
        _read_200(f"{base_url.rstrip('/')}{asset}", timeout_seconds)
        verified.append(asset)
    return verified


def run_frontend_probe(base_url: str) -> dict:
    from playwright.sync_api import sync_playwright

    assets = verify_frontend_assets(base_url)
    page_errors: list[str] = []
    console_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on(
                "console",
                lambda message: console_errors.append(message.text)
                if message.type == "error"
                else None,
            )
            page.goto(base_url, wait_until="domcontentloaded", timeout=15000)
            page.locator(".app-shell").wait_for(state="visible", timeout=15000)
            booted = bool(page.evaluate(
                "Boolean(window.__VK_UI_BOOTED__ === true && document.querySelector('.app-shell'))"
            ))
            if not booted:
                raise RuntimeError("React-интерфейс не подтвердил успешный запуск")
        finally:
            browser.close()
    return {
        "ok": True,
        "assets": assets,
        "page_errors": page_errors,
        "console_errors": console_errors,
    }


def wait_for_ui_ready(window, timeout_seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    expression = "Boolean(window.__VK_UI_BOOTED__ === true && document.querySelector('.app-shell'))"
    while time.monotonic() < deadline:
        try:
            if bool(window.evaluate_js(expression)):
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


_fallback_lock = threading.Lock()
_fallback_opened = False


def open_browser_fallback(url: str) -> bool:
    global _fallback_opened
    with _fallback_lock:
        if _fallback_opened:
            return False
        _fallback_opened = True

    def _open() -> None:
        try:
            webbrowser.open(url, new=1)
        except Exception:
            return

    threading.Thread(target=_open, name="vk-outreach-browser-fallback", daemon=True).start()
    return True
