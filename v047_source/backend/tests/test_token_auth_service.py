from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from app.vk.auth import (
    AuthBusyError,
    AuthIdentityMismatch,
    BrowserLaunchError,
    BrowserTokenAuthService,
    PlaywrightTokenProvider,
    VkIdentity,
)


class MemorySecretStore:
    def __init__(self):
        self.saved = {}

    def protect(self, plaintext: str) -> bytes:
        return f"encrypted:{plaintext[::-1]}".encode()

    def save_for_account(self, account_key: str, encrypted: bytes, fingerprint: str) -> None:
        self.saved[account_key] = (encrypted, fingerprint)


class FakeBrowser:
    def __init__(self, token="live-token", gate: asyncio.Event | None = None):
        self.token = token
        self.gate = gate
        self.calls = []

    async def acquire_token(self, profile_path, on_status):
        self.calls.append(profile_path)
        on_status("waiting_user", "Ожидаю вход")
        if self.gate:
            await self.gate.wait()
        on_status("token_captured", "Токен получен")
        return self.token


@dataclass
class FakeValidator:
    identity: VkIdentity

    async def validate(self, token: str) -> VkIdentity:
        assert token == "live-token"
        return self.identity


@pytest.mark.asyncio
async def test_token_is_validated_encrypted_and_stored(tmp_path):
    secrets = MemorySecretStore()
    identity = VkIdentity(123, "Сергей", "Иванов", "https://vk.com/id123", "avatar")
    service = BrowserTokenAuthService(FakeBrowser(), FakeValidator(identity), secrets, tmp_path)

    result = await service.authorize("draft-1")

    assert result.identity == identity
    encrypted, fingerprint = secrets.saved["draft-1"]
    assert encrypted != b"live-token"
    assert len(fingerprint) == 16
    assert result.token_fingerprint == fingerprint
    assert result.profile_path.parent == tmp_path


@pytest.mark.asyncio
async def test_expected_vk_identity_cannot_be_silently_replaced(tmp_path):
    identity = VkIdentity(123, "Сергей", "Иванов", "", "")
    service = BrowserTokenAuthService(FakeBrowser(), FakeValidator(identity), MemorySecretStore(), tmp_path)

    with pytest.raises(AuthIdentityMismatch):
        await service.authorize("existing", expected_vk_user_id=999)


@pytest.mark.asyncio
async def test_authorization_is_single_flight_per_account(tmp_path):
    gate = asyncio.Event()
    identity = VkIdentity(123, "Сергей", "Иванов", "", "")
    service = BrowserTokenAuthService(FakeBrowser(gate=gate), FakeValidator(identity), MemorySecretStore(), tmp_path)

    first = asyncio.create_task(service.authorize("same"))
    await asyncio.sleep(0)
    with pytest.raises(AuthBusyError):
        await service.authorize("same")
    gate.set()
    await first


@pytest.mark.asyncio
async def test_different_accounts_can_authorize_independently(tmp_path):
    identity = VkIdentity(123, "Сергей", "Иванов", "", "")
    browser = FakeBrowser()
    service = BrowserTokenAuthService(browser, FakeValidator(identity), MemorySecretStore(), tmp_path)

    await asyncio.gather(service.authorize("one"), service.authorize("two"))
    assert len(browser.calls) == 2


class FailingChromium:
    def __init__(self):
        self.channels = []

    async def launch_persistent_context(self, **kwargs):
        self.channels.append(kwargs.get("channel", "bundled"))
        raise RuntimeError("access_token=must-not-leak https://secret.invalid/")


class FailingPlaywright:
    def __init__(self):
        self.chromium = FailingChromium()


@pytest.mark.asyncio
async def test_browser_launch_error_is_actionable_and_does_not_leak_secrets(tmp_path):
    provider = PlaywrightTokenProvider()
    playwright = FailingPlaywright()

    with pytest.raises(BrowserLaunchError) as caught:
        await provider._launch(playwright, tmp_path / "profile")

    message = str(caught.value)
    assert playwright.chromium.channels == ["msedge", "bundled"]
    assert "Microsoft Edge" in message
    assert "встроенный Chromium" in message
    assert "RuntimeError" in message
    assert "must-not-leak" not in message
    assert "secret.invalid" not in message
