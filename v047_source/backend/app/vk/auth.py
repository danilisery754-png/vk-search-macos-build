from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import unquote, urlparse, urlsplit

from playwright.async_api import BrowserContext, Page, async_playwright

from app.core.enums import AttemptState
from app.vk.client import VkApiClient


StatusCallback = Callable[[str, str], None]


class AuthError(RuntimeError):
    pass


class AuthTokenRejected(AuthError):
    """VK explicitly rejected a captured access token."""


class AuthBusyError(AuthError):
    pass


class AuthIdentityMismatch(AuthError):
    pass


class AuthTimeout(AuthError):
    pass


class BrowserLaunchError(AuthError):
    pass


@dataclass(frozen=True, slots=True)
class VkIdentity:
    vk_user_id: int
    first_name: str
    last_name: str
    profile_url: str
    avatar_url: str


@dataclass(frozen=True, slots=True)
class AuthorizationResult:
    identity: VkIdentity
    token_fingerprint: str
    profile_path: Path


class BrowserTokenProvider(Protocol):
    async def acquire_token(
        self,
        profile_path: Path,
        on_status: StatusCallback,
        confirmation_event: asyncio.Event | None = None,
    ) -> str: ...


class IdentityValidator(Protocol):
    async def validate(self, token: str) -> VkIdentity: ...


class TokenSecretStore(Protocol):
    def protect(self, plaintext: str) -> bytes: ...
    def save_for_account(self, account_key: str, encrypted: bytes, fingerprint: str) -> None: ...


class BrowserTokenAuthService:
    def __init__(
        self,
        browser: BrowserTokenProvider,
        validator: IdentityValidator,
        secrets: TokenSecretStore,
        profiles_root: Path,
    ):
        self.browser = browser
        self.validator = validator
        self.secrets = secrets
        self.profiles_root = profiles_root
        self._active: set[str] = set()
        self._guard = asyncio.Lock()

    async def authorize(
        self,
        account_key: str,
        *,
        expected_vk_user_id: int | None = None,
        on_status: StatusCallback | None = None,
        confirmation_event: asyncio.Event | None = None,
    ) -> AuthorizationResult:
        callback = on_status or (lambda _state, _message: None)
        safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", account_key).strip("._") or "account"
        async with self._guard:
            if safe_key in self._active:
                raise AuthBusyError("Авторизация этого аккаунта уже выполняется")
            self._active.add(safe_key)
        profile_path = self.profiles_root / safe_key
        profile_path.mkdir(parents=True, exist_ok=True)
        try:
            callback("opening", "Открываю защищённое окно VK")
            identity: VkIdentity | None = None
            token = ""
            for attempt in range(2):
                if confirmation_event is None:
                    token = await self.browser.acquire_token(profile_path, callback)
                else:
                    token = await self.browser.acquire_token(
                        profile_path,
                        callback,
                        confirmation_event,
                    )
                callback("validating", "Проверяю токен через VK API users.get")
                try:
                    identity = await self.validator.validate(token)
                    break
                except AuthTokenRejected:
                    token = ""
                    if attempt:
                        raise
                    callback(
                        "refreshing_token",
                        "Первый токен VK отклонён; автоматически получаю новый тем же способом",
                    )
            if identity is None:
                raise AuthError("VK не подтвердил аккаунт")
            if expected_vk_user_id is not None and identity.vk_user_id != expected_vk_user_id:
                raise AuthIdentityMismatch(
                    f"Ожидался VK ID {expected_vk_user_id}, выполнен вход в VK ID {identity.vk_user_id}"
                )
            fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
            encrypted = self.secrets.protect(token)
            self.secrets.save_for_account(account_key, encrypted, fingerprint)
            token = ""
            callback("completed", "Аккаунт подключён")
            return AuthorizationResult(identity, fingerprint, profile_path)
        finally:
            async with self._guard:
                self._active.discard(safe_key)


class VkIdentityValidator:
    async def validate(self, token: str) -> VkIdentity:
        client = VkApiClient(token)
        try:
            result = await client.validate_identity()
        finally:
            await client.aclose()
        if result.state is AttemptState.AUTH_REQUIRED:
            raise AuthTokenRejected(result.reason or "VK отклонил токен")
        if result.state is not AttemptState.SENT or not result.raw:
            raise AuthError(result.reason or "VK не подтвердил аккаунт")
        raw = result.raw
        user_id = int(raw["id"])
        return VkIdentity(
            vk_user_id=user_id,
            first_name=str(raw.get("first_name", "")),
            last_name=str(raw.get("last_name", "")),
            profile_url=f"https://vk.com/id{user_id}",
            avatar_url=str(raw.get("photo_100", "")),
        )


def _token_from_url(url: str) -> str | None:
    token = PlaywrightTokenProvider._extract_browser_token(url)
    return token or None


class PlaywrightTokenProvider:
    """Known-good VK flow: plain VK login -> VKHost vk.com -> VK OAuth -> direct URL token capture."""

    VK_LOGIN_URL = "https://vk.com/"
    VKHOST_URL = "https://vkhost.github.io/"
    AUTH_SURFACE_HOSTS = {"oauth.vk.com", "oauth.vk.ru", "id.vk.com", "id.vk.ru"}

    def __init__(self, *, timeout_seconds: int = 300):
        self.timeout_seconds = timeout_seconds
        self._observed_token_urls: deque[tuple[str, Any, int | None]] = deque()
        self._watched_page_ids: set[tuple[int | None, int]] = set()

    async def _launch(self, playwright, profile_path: Path) -> BrowserContext:
        self._scrub_sensitive_navigation_artifacts(profile_path)
        common = {
            "user_data_dir": str(profile_path),
            "headless": False,
            "no_viewport": True,
            "args": ["--start-maximized", "--disable-blink-features=AutomationControlled"],
        }
        try:
            return await playwright.chromium.launch_persistent_context(channel="msedge", **common)
        except Exception as edge_error:
            try:
                return await playwright.chromium.launch_persistent_context(**common)
            except Exception as chromium_error:
                raise BrowserLaunchError(
                    "Не удалось открыть Microsoft Edge и встроенный Chromium "
                    f"({type(edge_error).__name__}; {type(chromium_error).__name__}). "
                    "Переустановите приложение или откройте раздел диагностики."
                ) from chromium_error

    async def acquire_token(
        self,
        profile_path: Path,
        on_status: StatusCallback,
        confirmation_event: asyncio.Event | None = None,
    ) -> str:
        profile_path.mkdir(parents=True, exist_ok=True)
        async with async_playwright() as playwright:
            context = await self._launch(playwright, profile_path)
            context_id = id(context)
            try:
                await self._discard_stale_token_pages(context)
                self._watch_context(context)
                gate = confirmation_event or asyncio.Event()
                if confirmation_event is None:
                    gate.set()
                return await self._acquire_token_in_context(context, on_status, gate)
            finally:
                self._drop_context_observations(context_id)
                await self._blank_pages(context)
                await context.close()

    async def _acquire_token_in_context(
        self,
        context: BrowserContext,
        on_status: StatusCallback,
        confirmation_event: asyncio.Event,
    ) -> str:
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(self.VK_LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)

        if not confirmation_event.is_set():
            on_status("waiting_user", "Войдите в VK и нажмите «Я вошёл в VK» в приложении")
            try:
                await asyncio.wait_for(confirmation_event.wait(), timeout=self.timeout_seconds)
            except TimeoutError as exc:
                raise AuthTimeout("Вход в VK не подтверждён за 5 минут") from exc

        await self._drain_plain_continue_gates_in_context(context, on_status=on_status, timeout=4.0)
        on_status("requesting_token", "Вход подтверждён; запускаю проверенный VKHost-поток получения токена")
        helper_page = await context.new_page()
        await helper_page.goto(self.VKHOST_URL, wait_until="domcontentloaded", timeout=60_000)
        token_url = await self._drive_vkhost_flow(
            helper_page,
            timeout=float(self.timeout_seconds),
            on_status=on_status,
        )
        token = self._extract_browser_token(token_url)
        if not token:
            raise AuthTimeout("VK OAuth завершился без access_token")
        on_status("token_captured", "Токен прочитан из адресной строки; проверяю users.get")
        return token

    def _watch_context(self, context: BrowserContext) -> None:
        try:
            context.on("page", self._watch_page)
        except Exception:
            pass
        try:
            context.on("request", self._watch_request)
        except Exception:
            pass
        for page in list(getattr(context, "pages", []) or []):
            self._watch_page(page)

    @staticmethod
    def _page_context_id(page: Any) -> int | None:
        try:
            context = page.context
        except Exception:
            return None
        return id(context) if context is not None else None

    def _record_navigation_url(self, page: Any, url: str) -> None:
        current = str(url or "")
        if self._extract_browser_token(current):
            self._observed_token_urls.append((current, page, self._page_context_id(page)))

    def _watch_request(self, request: Any) -> None:
        try:
            frame = request.frame
            page = frame.page if frame is not None else None
        except Exception:
            page = None
        if page is not None:
            self._record_navigation_url(page, str(getattr(request, "url", "") or ""))

    def _watch_page(self, page: Any) -> None:
        context_id = self._page_context_id(page)
        page_key = (context_id, id(page))
        if page_key in self._watched_page_ids:
            return
        self._watched_page_ids.add(page_key)
        self._record_navigation_url(page, str(getattr(page, "url", "") or ""))
        try:
            page.on(
                "framenavigated",
                lambda frame: self._record_navigation_url(page, str(getattr(frame, "url", "") or "")),
            )
        except Exception:
            pass

    def _drop_context_observations(self, context_id: int) -> None:
        self._observed_token_urls = deque(
            item for item in self._observed_token_urls if item[2] not in (context_id, None)
        )
        self._watched_page_ids = {item for item in self._watched_page_ids if item[0] != context_id}

    @staticmethod
    def _scrub_sensitive_navigation_artifacts(profile_path: Path) -> None:
        """Discard restored tabs/history while preserving VK cookies/site storage."""
        root = Path(profile_path)
        if not root.exists():
            return
        prefixes = (
            "History",
            "Visited Links",
            "Top Sites",
            "Shortcuts",
            "Network Action Predictor",
            "Current Session",
            "Current Tabs",
            "Last Session",
            "Last Tabs",
        )
        for base in (root, root / "Default"):
            if not base.exists():
                continue
            try:
                children = list(base.iterdir())
            except OSError:
                children = []
            for path in children:
                if path.is_file() and any(path.name == prefix or path.name.startswith(prefix + "-") for prefix in prefixes):
                    path.unlink(missing_ok=True)
            for relative in ("Sessions", "Cache", "Code Cache", "GPUCache"):
                target = base / relative
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
            service_cache = base / "Service Worker" / "CacheStorage"
            if service_cache.exists():
                shutil.rmtree(service_cache, ignore_errors=True)

    async def _discard_stale_token_pages(self, context: BrowserContext) -> None:
        context_id = id(context)
        self._observed_token_urls = deque(
            item for item in self._observed_token_urls if item[2] not in (context_id, None)
        )
        for candidate in list(getattr(context, "pages", []) or []):
            current = str(getattr(candidate, "url", "") or "")
            if self._extract_browser_token(current):
                await self._blank_captured_token_page(candidate)

    @staticmethod
    def _extract_browser_token(url: str) -> str:
        """Copy access_token directly from the browser address string."""
        current = str(url or "")
        match = re.search(r"(?:[?#&])access_token=([^&#]+)", current, flags=re.I)
        if match is None:
            return ""
        return unquote(match.group(1)).strip()

    async def _visible_page_urls(self, page: Any) -> list[str]:
        urls: list[str] = []
        try:
            current = str(getattr(page, "url", "") or "")
            if current:
                urls.append(current)
        except Exception:
            pass
        try:
            frames = list(getattr(page, "frames", []) or [])
        except Exception:
            frames = []
        for frame in frames:
            try:
                current = str(getattr(frame, "url", "") or "")
            except Exception:
                continue
            if current and current not in urls:
                urls.append(current)
        try:
            current = str(
                await asyncio.wait_for(page.evaluate("() => window.location.href"), timeout=0.5) or ""
            )
            if current and current not in urls:
                urls.append(current)
        except Exception:
            pass
        return urls

    async def _capture_token_url_from_devtools(self, context: Any, pages: list[Any]) -> str:
        new_session = getattr(context, "new_cdp_session", None)
        if not callable(new_session):
            return ""
        for page in pages:
            session = None
            try:
                session = await new_session(page)
                payload = await asyncio.wait_for(session.send("Target.getTargets"), timeout=1.0)
                infos = payload.get("targetInfos", []) if isinstance(payload, dict) else []
                for info in infos:
                    if not isinstance(info, dict) or str(info.get("type") or "") != "page":
                        continue
                    current = str(info.get("url") or "")
                    if not self._extract_browser_token(current):
                        continue
                    target_id = str(info.get("targetId") or "")
                    if target_id:
                        try:
                            await session.send("Target.closeTarget", {"targetId": target_id})
                        except Exception:
                            pass
                    return current
            except Exception:
                continue
            finally:
                if session is not None:
                    try:
                        await session.detach()
                    except Exception:
                        pass
        return ""

    async def _capture_token_url_from_context(self, context: Any) -> tuple[str, Any | None]:
        context_id = id(context)
        retained: deque[tuple[str, Any, int | None]] = deque()
        while self._observed_token_urls:
            current, page, owner_context_id = self._observed_token_urls.popleft()
            if owner_context_id not in (None, context_id):
                retained.append((current, page, owner_context_id))
                continue
            if self._extract_browser_token(current):
                self._observed_token_urls.extendleft(reversed(retained))
                return current, page
        self._observed_token_urls.extendleft(reversed(retained))

        try:
            pages = list(getattr(context, "pages", []) or [])
        except Exception:
            pages = []
        for candidate in pages:
            try:
                visible_urls = await self._visible_page_urls(candidate)
            except Exception:
                continue
            for current in visible_urls:
                if self._extract_browser_token(current):
                    return current, candidate
        devtools_url = await self._capture_token_url_from_devtools(context, pages)
        if devtools_url:
            return devtools_url, None
        return "", None

    @staticmethod
    def _is_vk_auth_surface_url(url: str) -> bool:
        try:
            host = (urlsplit(str(url or "")).hostname or "").casefold()
        except Exception:
            return False
        return host in PlaywrightTokenProvider.AUTH_SURFACE_HOSTS

    def _latest_vk_auth_surface_page(self, context: Any) -> Any | None:
        for candidate in reversed(list(getattr(context, "pages", []) or [])):
            if self._is_vk_auth_surface_url(str(getattr(candidate, "url", "") or "")):
                return candidate
        return None

    async def _vk_auth_surface_fingerprint(self, page: Any) -> tuple[str, str]:
        current = str(getattr(page, "url", "") or "")
        try:
            body = await page.locator("body").inner_text(timeout=800)
        except Exception:
            try:
                body = await page.content()
            except Exception:
                body = ""
        return current, str(body or "")[:6000]

    async def _click_known_vk_auth_modal_if_present(self, page: Any) -> bool:
        try:
            dialogs = page.locator('[role="dialog"][aria-modal="true"]')
            count = await dialogs.count()
        except Exception:
            return False
        title_pattern = re.compile(r"^Этот номер (?:ещё|еще) ваш\?$", re.I)
        yes_pattern = re.compile(r"^Да$", re.I)
        for index in range(min(count, 8)):
            dialog = dialogs.nth(index)
            try:
                if not await dialog.is_visible():
                    continue
                title = dialog.get_by_text(title_pattern, exact=True)
                if not await title.count() or not await title.first.is_visible():
                    continue
                yes = dialog.get_by_role("button", name=yes_pattern, exact=True)
                if not await yes.count():
                    raise RuntimeError("В окне «Этот номер ещё ваш?» не найдена кнопка «Да»")
                button = yes.first
                if not await button.is_visible() or not await button.is_enabled():
                    raise RuntimeError("Кнопка «Да» в окне подтверждения недоступна")
                try:
                    await button.click(timeout=3000, no_wait_after=True)
                except TypeError:
                    await button.click(timeout=3000)
                try:
                    await dialog.wait_for(state="hidden", timeout=5000)
                except Exception:
                    pass
                return True
            except RuntimeError:
                raise
            except Exception as exc:
                raise RuntimeError(
                    f"Не удалось подтвердить окно «Этот номер ещё ваш?»: {type(exc).__name__}"
                ) from exc
        return False

    async def _find_visible_plain_continue(self, page: Any) -> Any | None:
        """Find only the transient plain Continue gate, never Continue as <name>."""
        pattern = re.compile(r"^(?:Продолжить|Continue)$", re.I)
        try:
            locators = (
                page.get_by_role("button", name=pattern, exact=True),
                page.get_by_role("link", name=pattern, exact=True),
                page.get_by_text(pattern, exact=True),
            )
        except Exception:
            return None
        for locator in locators:
            try:
                count = await locator.count()
                for index in range(min(count, 8)):
                    candidate = locator.nth(index)
                    if await candidate.is_visible() and await candidate.is_enabled():
                        return candidate
            except Exception:
                continue
        return None

    async def _find_visible_vk_auth_action(self, page: Any) -> Any | None:
        patterns = (
            re.compile(r"^Продолжить как(?:\s|$)", re.I),
            re.compile(r"^(?:Разрешить|Это я|Подтвердить|Allow|Confirm|Continue as(?:\s|$))$", re.I),
        )
        for pattern in patterns:
            try:
                locators = (
                    page.get_by_role("button", name=pattern),
                    page.get_by_role("link", name=pattern),
                    page.get_by_text(pattern),
                )
            except Exception:
                continue
            for locator in locators:
                try:
                    count = await locator.count()
                    for index in range(min(count, 8)):
                        candidate = locator.nth(index)
                        if await candidate.is_visible() and await candidate.is_enabled():
                            return candidate
                except Exception:
                    continue
        return None

    async def _click_plain_continue(self, page: Any) -> bool:
        action = await self._find_visible_plain_continue(page)
        if action is None:
            return False
        try:
            await action.click(timeout=3000, no_wait_after=True)
        except TypeError:
            await action.click(timeout=3000)
        return True

    async def _drain_plain_continue_gates_in_context(
        self,
        context: Any,
        *,
        on_status: StatusCallback | None = None,
        timeout: float = 4.0,
    ) -> int:
        callback = on_status or (lambda _state, _message: None)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(float(timeout), 0.2)
        clicks = 0
        idle_rounds = 0
        while loop.time() < deadline:
            clicked = False
            for candidate in reversed(list(getattr(context, "pages", []) or [])):
                if await self._click_plain_continue(candidate):
                    clicks += 1
                    clicked = True
                    idle_rounds = 0
                    callback("vk_continue_gate", "Нажимаю промежуточную кнопку VK «Продолжить»")
                    await asyncio.sleep(0.2)
                    break
            if clicked:
                continue
            idle_rounds += 1
            if idle_rounds >= 5:
                break
            await asyncio.sleep(0.1)
        return clicks

    async def _drive_vkhost_flow(
        self,
        page: Any,
        *,
        timeout: float = 45.0,
        on_status: StatusCallback | None = None,
    ) -> str:
        callback = on_status or (lambda _state, _message: None)
        exact_vk = re.compile(r"^vk\.com$", re.I)
        exact_candidates = (
            page.get_by_role("button", name=exact_vk),
            page.get_by_role("link", name=exact_vk),
            page.get_by_text(exact_vk),
        )
        selected = None
        for locator in exact_candidates:
            try:
                if await locator.count() and await locator.first.is_visible():
                    selected = locator.first
                    break
            except Exception:
                continue
        if selected is None:
            raise RuntimeError("На VKHost не найдена точная кнопка «vk.com»")
        callback("vkhost_selected", "VKHost открыт; выбираю vk.com")
        try:
            await selected.click(timeout=5000, no_wait_after=True)
        except TypeError:
            await selected.click(timeout=5000)

        context = page.context

        async def capture_token() -> str:
            captured_url, captured_page = await self._capture_token_url_from_context(context)
            if captured_url:
                await self._blank_captured_token_page(captured_page)
            return captured_url

        direct_url = await capture_token()
        if direct_url:
            return direct_url

        loop = asyncio.get_running_loop()
        overall_deadline = loop.time() + max(float(timeout), 1.0)
        confirmations_left = 4
        confirmations_done = 0
        clicked_states: set[tuple[str, str]] = set()
        last_progress_at = loop.time()

        while loop.time() < overall_deadline:
            token_url = await capture_token()
            if token_url:
                return token_url

            auth_page = self._latest_vk_auth_surface_page(context)
            if auth_page is None:
                await asyncio.sleep(0.1)
                continue

            if await self._click_known_vk_auth_modal_if_present(auth_page):
                callback("vk_phone_confirmed", "Подтвердил окно «Этот номер ещё ваш?»")
                last_progress_at = loop.time()
                await asyncio.sleep(0.1)
                continue

            if await self._click_plain_continue(auth_page):
                callback("vk_continue_gate", "Нажимаю промежуточную кнопку VK «Продолжить»")
                last_progress_at = loop.time()
                await asyncio.sleep(0.15)
                continue

            action = await self._find_visible_vk_auth_action(auth_page)
            if action is not None and confirmations_left > 0:
                state = await self._vk_auth_surface_fingerprint(auth_page)
                if state not in clicked_states:
                    clicked_states.add(state)
                    callback("vk_confirming", "Нажимаю подтверждение VK («Продолжить как…» / «Разрешить»)")
                    try:
                        await action.click(timeout=3000, no_wait_after=True)
                    except TypeError:
                        await action.click(timeout=3000)
                    confirmations_left -= 1
                    confirmations_done += 1
                    last_progress_at = loop.time()
                    await asyncio.sleep(0.15)
                    continue

            if confirmations_done >= 4 and loop.time() - last_progress_at >= 3.0:
                raise RuntimeError("VK показал несколько подтверждений, но access_token не появился")
            if confirmations_done > 0 and loop.time() - last_progress_at >= 12.0:
                raise RuntimeError(
                    f"После подтверждения VK #{confirmations_done} не появился access_token"
                )
            await asyncio.sleep(0.1)

        for _ in range(8):
            token_url = await capture_token()
            if token_url:
                return token_url
            await asyncio.sleep(0.1)
        raise AuthTimeout(
            "VK ещё ждёт вход/2FA/CAPTCHA/подтверждение; завершите его в открытом окне"
        )

    @staticmethod
    async def _blank_captured_token_page(page: Any) -> None:
        if page is None:
            return
        try:
            await page.goto("about:blank", wait_until="load", timeout=10_000)
        except Exception:
            pass

    @staticmethod
    async def _blank_pages(context: BrowserContext) -> None:
        for page in list(getattr(context, "pages", []) or []):
            try:
                await page.goto("about:blank", wait_until="commit", timeout=2_000)
            except Exception:
                pass


class PlaywrightMessagesBrowser:
    """Открывает сообщения VK в постоянном профиле и живёт до закрытия окна."""

    async def open_messages(self, profile_path: Path) -> None:
        profile_path.mkdir(parents=True, exist_ok=True)
        async with async_playwright() as playwright:
            context = await PlaywrightTokenProvider()._launch(playwright, profile_path)
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto("https://vk.com/im", wait_until="domcontentloaded", timeout=60_000)
                while context.pages:
                    await asyncio.sleep(0.5)
            finally:
                await context.close()
