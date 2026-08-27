from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from app.vk.auth import AuthTokenRejected, BrowserTokenAuthService, PlaywrightTokenProvider, VkIdentity


class MemorySecretStore:
    def __init__(self):
        self.saved = {}

    def protect(self, plaintext: str) -> bytes:
        return plaintext.encode()

    def save_for_account(self, account_key: str, encrypted: bytes, fingerprint: str) -> None:
        self.saved[account_key] = (encrypted, fingerprint)


def test_browser_token_parser_copies_exact_visible_address_token():
    url = (
        "https://oauth.vk.ru/blank.html#access_token="
        "vk1.a.TEST-TOKEN_123&expires_in=0&user_id=77"
    )
    assert PlaywrightTokenProvider._extract_browser_token(url) == "vk1.a.TEST-TOKEN_123"


@pytest.mark.asyncio
async def test_visible_address_fallback_reads_window_location_when_page_url_lags():
    token_url = "https://oauth.vk.ru/blank.html#access_token=VISIBLE_TOKEN&user_id=77"

    class Page:
        url = "https://oauth.vk.ru/blank.html"
        frames = []

        async def evaluate(self, expression):
            assert "location.href" in expression
            return token_url

    page = Page()
    context = type("Context", (), {"pages": [page]})()
    provider = PlaywrightTokenProvider()

    captured_url, captured_page = await provider._capture_token_url_from_context(context)

    assert captured_url == token_url
    assert captured_page is page


@pytest.mark.asyncio
async def test_continue_as_action_matches_real_vk_button_text():
    class Candidate:
        def __init__(self, visible: bool):
            self.visible = visible

        async def is_visible(self):
            return self.visible

        async def is_enabled(self):
            return self.visible

    class Locator:
        def __init__(self, matched: bool):
            self.matched = matched

        async def count(self):
            return 1 if self.matched else 0

        def nth(self, _index):
            return Candidate(True)

    class Page:
        def get_by_role(self, role, name=None):
            matched = role == "button" and bool(name.search("Продолжить как Сергей"))
            return Locator(matched)

        def get_by_text(self, name):
            return Locator(bool(name.search("Продолжить как Сергей")))

    action = await PlaywrightTokenProvider()._find_visible_vk_auth_action(Page())
    assert action is not None


@pytest.mark.asyncio
async def test_navigation_event_token_is_captured_even_before_page_url_updates():
    provider = PlaywrightTokenProvider()
    page = type("Page", (), {"url": "about:blank", "frames": []})()
    context = type("Context", (), {"pages": [page]})()
    token_url = "https://oauth.vk.ru/blank.html#access_token=EVENT_TOKEN&user_id=77"

    provider._record_navigation_url(page, token_url)
    captured_url, captured_page = await provider._capture_token_url_from_context(context)

    assert captured_url == token_url
    assert captured_page is page


@pytest.mark.asyncio
async def test_manual_flow_opens_plain_vk_then_waits_for_confirmation_before_vkhost(monkeypatch):
    class Page:
        def __init__(self, url="about:blank"):
            self.url = url
            self.gotos = []

        async def goto(self, url, **_kwargs):
            self.url = url
            self.gotos.append(url)

    class Context:
        def __init__(self):
            self.pages = [Page()]
            self.helper = None

        async def new_page(self):
            self.helper = Page()
            self.pages.append(self.helper)
            return self.helper

    provider = PlaywrightTokenProvider(timeout_seconds=2)
    context = Context()
    gate = asyncio.Event()
    statuses = []

    async def fake_drive(page, *, timeout, on_status=None):
        assert page is context.helper
        assert page.url == provider.VKHOST_URL
        return "https://oauth.vk.ru/blank.html#access_token=LIVE&user_id=77"

    monkeypatch.setattr(provider, "_drive_vkhost_flow", fake_drive)

    task = asyncio.create_task(
        provider._acquire_token_in_context(context, lambda *args: statuses.append(args), gate)
    )
    await asyncio.sleep(0)

    assert context.pages[0].gotos == ["https://vk.com/"]
    assert context.helper is None
    assert task.done() is False

    gate.set()
    token = await asyncio.wait_for(task, timeout=1)

    assert token == "LIVE"
    assert context.helper is not None
    assert context.helper.gotos == [provider.VKHOST_URL]


class SequencedBrowser:
    def __init__(self):
        self.tokens = ["expired-new-token", "fresh-token"]
        self.calls = 0

    async def acquire_token(self, profile_path, on_status, confirmation_event=None):
        self.calls += 1
        return self.tokens.pop(0)


@dataclass
class RetryValidator:
    identity: VkIdentity
    calls: int = 0

    async def validate(self, token: str) -> VkIdentity:
        self.calls += 1
        if token == "expired-new-token":
            raise AuthTokenRejected("VK token expired")
        assert token == "fresh-token"
        return self.identity


@pytest.mark.asyncio
async def test_invalid_first_captured_token_is_refreshed_once_automatically(tmp_path):
    browser = SequencedBrowser()
    validator = RetryValidator(VkIdentity(77, "A", "B", "", ""))
    service = BrowserTokenAuthService(browser, validator, MemorySecretStore(), tmp_path)

    result = await service.authorize("account-77")

    assert result.identity.vk_user_id == 77
    assert browser.calls == 2
    assert validator.calls == 2

@pytest.mark.asyncio
async def test_token_scan_falls_back_to_chrome_devtools_target_list():
    token_url = "https://oauth.vk.ru/blank.html#access_token=CDP_TOKEN&user_id=77"

    class Session:
        detached = False
        closed_target = None

        async def send(self, method, params=None):
            if method == "Target.closeTarget":
                self.closed_target = params["targetId"]
                return {"success": True}
            assert method == "Target.getTargets"
            return {
                "targetInfos": [
                    {"targetId": "feed", "type": "page", "url": "https://vk.com/feed"},
                    {"targetId": "token-tab", "type": "page", "url": token_url},
                ]
            }

        async def detach(self):
            self.detached = True

    class Page:
        url = "https://vk.com/feed"
        frames = []

        async def evaluate(self, _expression):
            return self.url

    session = Session()

    class Context:
        pages = [Page()]

        async def new_cdp_session(self, page):
            assert page is self.pages[0]
            return session

    provider = PlaywrightTokenProvider()
    captured_url, captured_page = await provider._capture_token_url_from_context(Context())

    assert captured_url == token_url
    assert captured_page is None
    assert session.closed_target == "token-tab"
    assert session.detached is True


@pytest.mark.asyncio
async def test_known_vk_phone_modal_clicks_exact_yes_before_oauth_continue():
    class Marker:
        @property
        def first(self):
            return self

        async def count(self):
            return 1

        async def is_visible(self):
            return True

    class YesButton(Marker):
        def __init__(self, dialog):
            self.dialog = dialog

        async def is_enabled(self):
            return True

        async def click(self, **_kwargs):
            self.dialog.visible = False
            self.dialog.yes_clicks += 1

    class Dialog(Marker):
        def __init__(self):
            self.visible = True
            self.yes_clicks = 0

        async def is_visible(self):
            return self.visible

        def get_by_text(self, _name, exact=False):
            return Marker()

        def get_by_role(self, role, name=None, exact=False):
            return YesButton(self) if role == "button" and exact else Marker()

        async def wait_for(self, state, timeout):
            assert state == "hidden"
            assert not self.visible

    class DialogList:
        def __init__(self, dialog):
            self.dialog = dialog

        async def count(self):
            return 1

        def nth(self, _index):
            return self.dialog

    dialog = Dialog()
    page = type("Page", (), {"locator": lambda self, _selector: DialogList(dialog)})()
    provider = PlaywrightTokenProvider()

    handled = await provider._click_known_vk_auth_modal_if_present(page)

    assert handled is True
    assert dialog.yes_clicks == 1
