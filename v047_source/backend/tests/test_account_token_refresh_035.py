from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine

from app.core.enums import AttemptState
from app.db.base import Base
from app.services.accounts import AccountService
from app.vk.client import VkActionResult


class GateAwareAuth:
    def __init__(self):
        self.started = asyncio.Event()
        self.released = asyncio.Event()
        self.confirmation_event = None

    async def authorize(self, account_key, *, expected_vk_user_id=None, on_status=None, confirmation_event=None):
        self.confirmation_event = confirmation_event
        on_status("waiting_user", "Войдите в VK и нажмите кнопку")
        self.started.set()
        await confirmation_event.wait()
        self.released.set()
        raise RuntimeError("stop-after-confirm")


@pytest.mark.asyncio
async def test_manual_authorization_is_gated_by_explicit_i_logged_in_button(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'db.sqlite3'}")
    Base.metadata.create_all(engine)
    service = AccountService(engine, tmp_path / "profiles", tmp_path / "secret.key")
    auth = GateAwareAuth()
    service.auth = auth

    job = service.start_authorization()
    await asyncio.wait_for(auth.started.wait(), timeout=1)

    assert service.auth_status(job.id)["state"] == "waiting_user"
    assert auth.confirmation_event is not None
    assert auth.confirmation_event.is_set() is False

    service.confirm_authorization(job.id)
    await asyncio.wait_for(auth.released.wait(), timeout=1)
    assert auth.confirmation_event.is_set() is True


class FakeClient:
    tokens_seen: list[str] = []

    def __init__(self, token: str):
        self.token = token
        self.tokens_seen.append(token)

    async def aclose(self):
        pass

    async def action(self):
        if self.token == "old-token":
            return VkActionResult(AttemptState.AUTH_REQUIRED, error_code=5, error_class="auth")
        return VkActionResult(AttemptState.SENT, object_id=123)


@pytest.mark.asyncio
async def test_vk_operation_refreshes_expired_token_once_and_retries(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'db.sqlite3'}")
    Base.metadata.create_all(engine)
    service = AccountService(engine, tmp_path / "profiles", tmp_path / "secret.key")
    FakeClient.tokens_seen = []
    monkeypatch.setattr(service, "get_token", lambda _account_id: "old-token")
    refresh_calls = []

    async def refresh(account_id, **_kwargs):
        refresh_calls.append(account_id)
        return "new-token"

    monkeypatch.setattr(service, "refresh_token", refresh, raising=False)

    result = await service.run_vk(
        77,
        lambda client: client.action(),
        client_factory=FakeClient,
    )

    assert result.state is AttemptState.SENT
    assert result.object_id == 123
    assert refresh_calls == [77]
    assert FakeClient.tokens_seen == ["old-token", "new-token"]

@pytest.mark.asyncio
async def test_vk_operation_returns_original_auth_error_if_saved_session_refresh_needs_interaction(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'db2.sqlite3'}")
    Base.metadata.create_all(engine)
    service = AccountService(engine, tmp_path / "profiles2", tmp_path / "secret2.key")
    monkeypatch.setattr(service, "get_token", lambda _account_id: "expired-token")

    class ExpiredClient:
        def __init__(self, _token):
            pass

        async def aclose(self):
            pass

        async def action(self):
            return VkActionResult(
                AttemptState.AUTH_REQUIRED,
                error_code=5,
                error_class="auth",
                reason="expired",
            )

    async def refresh(_account_id, **_kwargs):
        raise RuntimeError("password/2FA required")

    monkeypatch.setattr(service, "refresh_token", refresh)

    result = await service.run_vk(77, lambda client: client.action(), client_factory=ExpiredClient)

    assert result.state is AttemptState.AUTH_REQUIRED
    assert result.reason == "expired"

@pytest.mark.asyncio
async def test_saved_browser_session_refresh_replaces_expired_token_without_manual_gate(tmp_path):
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db.models import Account, AccountSecret
    from app.vk.auth import AuthorizationResult, VkIdentity

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'refresh-real.sqlite3'}")
    Base.metadata.create_all(engine)
    profiles = tmp_path / "profiles-real"
    service = AccountService(engine, profiles, tmp_path / "secret-real.key")

    with Session(engine) as session:
        account = Account(vk_user_id=77, first_name="Old", auth_status="ok")
        session.add(account)
        session.flush()
        stable_profile = profiles / f"account-{account.id}"
        stable_profile.mkdir(parents=True, exist_ok=True)
        session.add(
            AccountSecret(
                account_id=account.id,
                encrypted_token=service.protector.protect("old-token"),
                token_fingerprint="old",
                browser_profile=str(stable_profile),
            )
        )
        session.commit()
        account_id = account.id

    class SavedSessionAuth:
        def __init__(self):
            self.calls = []

        async def authorize(
            self,
            account_key,
            *,
            expected_vk_user_id=None,
            on_status=None,
            confirmation_event=None,
        ):
            self.calls.append((account_key, expected_vk_user_id, confirmation_event))
            assert confirmation_event is None
            encrypted = service.protector.protect("new-token")
            service.pending.save_for_account(account_key, encrypted, "new-fp")
            return AuthorizationResult(
                VkIdentity(77, "New", "Name", "https://vk.com/id77", "avatar"),
                "new-fp",
                stable_profile,
            )

    fake = SavedSessionAuth()
    service.auth = fake

    token = await service.refresh_token(account_id, failed_token="old-token", timeout_seconds=1)

    assert token == "new-token"
    assert fake.calls == [(f"account-{account_id}", 77, None)]
    with Session(engine) as session:
        account = session.get(Account, account_id)
        secret = session.scalar(select(AccountSecret).where(AccountSecret.account_id == account_id))
        assert account.auth_status == "ok"
        assert account.first_name == "New"
        assert secret.token_fingerprint == "new-fp"
