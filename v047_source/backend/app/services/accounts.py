from __future__ import annotations

import asyncio
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.core.secrets import DPAPIProtector
from app.core.enums import AttemptState, WorkItemState
from app.db.models import Account, AccountSecret, Dialog, WorkItem
from app.vk.auth import (
    AuthorizationResult,
    BrowserTokenAuthService,
    PlaywrightMessagesBrowser,
    PlaywrightTokenProvider,
    VkIdentityValidator,
)
from app.vk.client import VkActionResult, VkApiClient


T = TypeVar("T")


class PendingTokenStore:
    def __init__(self, protector: DPAPIProtector):
        self.protector = protector
        self.pending: dict[str, tuple[bytes, str]] = {}

    def protect(self, plaintext: str) -> bytes:
        return self.protector.protect(plaintext)

    def save_for_account(self, account_key: str, encrypted: bytes, fingerprint: str) -> None:
        self.pending[account_key] = (encrypted, fingerprint)

    def take(self, account_key: str) -> tuple[bytes, str]:
        return self.pending.pop(account_key)


@dataclass(slots=True)
class AuthJob:
    id: str
    state: str = "created"
    message: str = "Подготовка авторизации"
    account_id: int | None = None
    error: str = ""

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BrowserJob:
    id: str
    account_id: int
    state: str = "opening"
    message: str = "Открываю сообщения VK"
    error: str = ""

    def public(self) -> dict[str, Any]:
        return asdict(self)


class AccountService:
    def __init__(self, engine: Engine, profiles_root: Path, development_key: Path, *, messages_browser=None):
        self.engine = engine
        self.profiles_root = profiles_root.resolve()
        self.protector = DPAPIProtector(development_key)
        self.pending = PendingTokenStore(self.protector)
        self.auth = BrowserTokenAuthService(
            PlaywrightTokenProvider(), VkIdentityValidator(), self.pending, profiles_root
        )
        self.jobs: dict[str, AuthJob] = {}
        self.auth_confirmations: dict[str, asyncio.Event] = {}
        self.browser_jobs: dict[str, BrowserJob] = {}
        self.messages_browser = messages_browser or PlaywrightMessagesBrowser()
        self._open_accounts: set[int] = set()
        self._auth_accounts: set[int] = set()
        self._refresh_locks: dict[int, asyncio.Lock] = {}
        self._health_lock = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()

    def list_accounts(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.scalars(select(Account).order_by(Account.created_at)).all()
            assigned = dict(session.execute(
                select(WorkItem.assigned_account_id, func.count(WorkItem.id))
                .where(
                    WorkItem.assigned_account_id.is_not(None),
                    WorkItem.state.in_((
                        WorkItemState.ASSIGNED,
                        WorkItemState.PROCESSING,
                        WorkItemState.RETRY_WAIT,
                        WorkItemState.RECONCILE_REQUIRED,
                        WorkItemState.PAUSED,
                    )),
                )
                .group_by(WorkItem.assigned_account_id)
            ).all())
            profiles = {
                secret.account_id: secret.browser_profile
                for secret in session.scalars(select(AccountSecret)).all()
            }
            unread_dialogs = dict(session.execute(
                select(Dialog.account_id, func.count(Dialog.id))
                .where(Dialog.unread_count > 0)
                .group_by(Dialog.account_id)
            ).all())
            return [
                self._public_account(
                    row,
                    assigned_groups=int(assigned.get(row.id, 0)),
                    session_ok=bool(profiles.get(row.id)) and Path(profiles[row.id]).exists(),
                    unread_dialogs=int(unread_dialogs.get(row.id, 0)),
                )
                for row in rows
            ]

    def get_token(self, account_id: int) -> str:
        with Session(self.engine) as session:
            secret = session.scalar(select(AccountSecret).where(AccountSecret.account_id == account_id))
            if secret is None:
                raise ValueError("Для аккаунта не сохранён токен")
            encrypted = bytes(secret.encrypted_token)
        return self.protector.unprotect(encrypted)

    @staticmethod
    def classify_health_result(result: VkActionResult) -> tuple[str, str]:
        if result.state is AttemptState.SENT:
            return "alive", result.reason or "VK API подтвердил аккаунт."
        if result.error_class == "account_banned":
            return "blocked", result.reason or "VK сообщил о блокировке аккаунта."
        if result.error_class == "account_deactivated":
            return "deactivated", result.reason or "VK сообщил о деактивации аккаунта."
        if result.state is AttemptState.AUTH_REQUIRED:
            return "requires_login", result.reason or "Требуется повторный вход в VK."
        return "unknown", result.reason or "Не удалось надёжно проверить состояние аккаунта."

    async def check_health(self, *, force: bool = False, min_interval_seconds: float = 300.0) -> list[dict[str, Any]]:
        """Lightweight users.get health check without opening a browser or changing outreach state."""
        async with self._health_lock:
            now = datetime.utcnow()
            with Session(self.engine) as session:
                rows = list(session.scalars(select(Account).order_by(Account.id)).all())
                candidates = [
                    (int(row.id), row.auth_status, row.health_checked_at)
                    for row in rows
                    if force
                    or row.health_checked_at is None
                    or row.auth_status != "ok"
                    or (now - row.health_checked_at).total_seconds() >= max(float(min_interval_seconds), 0.0)
                ]

            for account_id, auth_status, _checked_at in candidates:
                if auth_status != "ok":
                    result = VkActionResult(
                        AttemptState.AUTH_REQUIRED,
                        error_class="authorization",
                        reason="Требуется повторный вход в VK.",
                    )
                else:
                    client = None
                    token = ""
                    try:
                        token = self.get_token(account_id)
                        client = VkApiClient(token)
                        result = await client.validate_identity()
                    except ValueError as exc:
                        result = VkActionResult(
                            AttemptState.AUTH_REQUIRED,
                            error_class="authorization",
                            reason=str(exc),
                        )
                    except Exception as exc:
                        result = VkActionResult(
                            AttemptState.TEMPORARY_ERROR,
                            error_class="health_check",
                            reason=f"Не удалось проверить аккаунт: {exc}",
                        )
                    finally:
                        token = ""
                        if client is not None:
                            await client.aclose()

                health_status, detail = self.classify_health_result(result)
                with Session(self.engine) as session:
                    account = session.get(Account, account_id)
                    if account is None:
                        continue
                    account.health_status = health_status
                    account.health_checked_at = datetime.utcnow()
                    account.health_detail = detail[:2000]
                    if health_status == "requires_login":
                        account.auth_status = "requires_login"
                    session.commit()
            return self.list_accounts()

    def start_authorization(self, account_id: int | None = None) -> AuthJob:
        if account_id is not None and account_id in self._open_accounts:
            raise ValueError("Сначала закройте окно сообщений этого аккаунта")
        job = AuthJob(id=uuid.uuid4().hex)
        confirmation_event = asyncio.Event()
        self.jobs[job.id] = job
        self.auth_confirmations[job.id] = confirmation_event
        if account_id is not None:
            self._auth_accounts.add(account_id)
        task = asyncio.create_task(self._run_authorization(job, account_id, confirmation_event))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return job

    def auth_status(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job.public()

    def confirm_authorization(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        confirmation_event = self.auth_confirmations.get(job_id)
        if confirmation_event is None:
            raise ValueError("Авторизация уже завершена")
        if job.state != "waiting_user":
            raise ValueError("Сначала дождитесь открытия VK и войдите в аккаунт")
        confirmation_event.set()
        job.state = "user_confirmed"
        job.message = "Вход подтверждён, получаю токен VK"
        return job.public()

    def start_open_messages(self, account_id: int) -> BrowserJob:
        if account_id in self._open_accounts:
            raise ValueError("Окно сообщений этого аккаунта уже открыто")
        if account_id in self._auth_accounts:
            raise ValueError("Для аккаунта уже выполняется авторизация")
        with Session(self.engine) as session:
            account = session.get(Account, account_id)
            secret = session.scalar(select(AccountSecret).where(AccountSecret.account_id == account_id))
            if account is None:
                raise KeyError(account_id)
            if secret is None or not secret.browser_profile:
                raise ValueError("Для аккаунта не найден сохранённый профиль браузера")
            profile_path = Path(secret.browser_profile).resolve()
        job = BrowserJob(id=uuid.uuid4().hex, account_id=account_id)
        self.browser_jobs[job.id] = job
        self._open_accounts.add(account_id)
        task = asyncio.create_task(self._run_open_messages(job, profile_path))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return job

    def browser_status(self, job_id: str) -> dict[str, Any]:
        job = self.browser_jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job.public()

    async def _run_open_messages(self, job: BrowserJob, profile_path: Path) -> None:
        job.state = "opened"
        try:
            await self.messages_browser.open_messages(profile_path)
            job.state, job.message = "closed", "Окно сообщений закрыто"
        except Exception as exc:
            job.state, job.error = "failed", str(exc)
        finally:
            self._open_accounts.discard(job.account_id)

    async def _run_authorization(
        self,
        job: AuthJob,
        account_id: int | None,
        confirmation_event: asyncio.Event,
    ) -> None:
        expected_vk_id: int | None = None
        if account_id is not None:
            with Session(self.engine) as session:
                account = session.get(Account, account_id)
                if account is None:
                    job.state, job.error = "failed", "Аккаунт не найден"
                    return
                expected_vk_id = account.vk_user_id

        def status(state: str, message: str) -> None:
            job.state, job.message = state, message

        try:
            auth_key = f"account-{account_id}" if account_id is not None else job.id
            result = await self.auth.authorize(
                auth_key,
                expected_vk_user_id=expected_vk_id,
                on_status=status,
                confirmation_event=confirmation_event,
            )
            encrypted, fingerprint = self.pending.take(auth_key)
            job.account_id = self._persist_authorization(
                result,
                encrypted,
                fingerprint,
                existing_account_id=account_id,
            )
            job.state, job.message = "completed", "Аккаунт подключён"
        except Exception as exc:
            self.pending.pending.pop(job.id, None)
            if account_id is not None:
                self.pending.pending.pop(f"account-{account_id}", None)
            job.state, job.error = "failed", str(exc)
        finally:
            self.auth_confirmations.pop(job.id, None)
            if account_id is not None:
                self._auth_accounts.discard(account_id)

    def _persist_authorization(
        self,
        result: AuthorizationResult,
        encrypted: bytes,
        fingerprint: str,
        *,
        existing_account_id: int | None,
    ) -> int:
        with Session(self.engine) as session:
            account = session.get(Account, existing_account_id) if existing_account_id is not None else None
            if account is None:
                account = session.scalar(
                    select(Account).where(Account.vk_user_id == result.identity.vk_user_id)
                )
            if account is None:
                account = Account(
                    vk_user_id=result.identity.vk_user_id,
                    first_name=result.identity.first_name,
                    last_name=result.identity.last_name,
                    profile_url=result.identity.profile_url,
                    avatar_url=result.identity.avatar_url,
                    auth_status="ok",
                    health_status="alive",
                    health_checked_at=datetime.utcnow(),
                    health_detail="VK API подтвердил аккаунт при авторизации.",
                )
                session.add(account)
                session.flush()
            elif account.vk_user_id != result.identity.vk_user_id:
                raise ValueError(
                    f"Ожидался VK ID {account.vk_user_id}, получен VK ID {result.identity.vk_user_id}"
                )
            else:
                account.first_name = result.identity.first_name
                account.last_name = result.identity.last_name
                account.profile_url = result.identity.profile_url
                account.avatar_url = result.identity.avatar_url
                account.auth_status = "ok"
                account.health_status = "alive"
                account.health_checked_at = datetime.utcnow()
                account.health_detail = "VK API подтвердил аккаунт при авторизации."
            account.last_checked_at = datetime.utcnow()
            account.last_error = ""

            stable_profile = self.profiles_root / f"account-{account.id}"
            current_profile = result.profile_path.resolve()
            if current_profile != stable_profile.resolve():
                if stable_profile.exists():
                    shutil.rmtree(current_profile, ignore_errors=True)
                else:
                    shutil.move(str(current_profile), str(stable_profile))

            secret = session.scalar(select(AccountSecret).where(AccountSecret.account_id == account.id))
            if secret is None:
                secret = AccountSecret(
                    account_id=account.id,
                    encrypted_token=encrypted,
                    token_fingerprint=fingerprint,
                    browser_profile=str(stable_profile),
                )
                session.add(secret)
            else:
                secret.encrypted_token = encrypted
                secret.token_fingerprint = fingerprint
                secret.browser_profile = str(stable_profile)
            session.commit()
            return int(account.id)

    async def refresh_token(
        self,
        account_id: int,
        *,
        failed_token: str | None = None,
        on_status: Callable[[str, str], None] | None = None,
        timeout_seconds: float = 90.0,
    ) -> str:
        """Refresh an expired token from the saved VK browser session without asking for a password.

        Calls for the same account are coalesced by a per-account lock. If another
        coroutine already replaced the failed token while we were waiting, the fresh
        stored token is returned without opening another browser.
        """

        lock = self._refresh_locks.setdefault(account_id, asyncio.Lock())
        async with lock:
            with Session(self.engine) as session:
                account = session.get(Account, account_id)
                if account is None:
                    raise KeyError(account_id)
                expected_vk_id = int(account.vk_user_id)

            current_token = self.get_token(account_id)
            if failed_token is not None and current_token != failed_token:
                return current_token
            current_token = ""

            if account_id in self._open_accounts:
                raise ValueError("Закройте окно сообщений VK перед автоматическим обновлением токена")
            if account_id in self._auth_accounts:
                raise ValueError("Для аккаунта уже выполняется авторизация")

            self._auth_accounts.add(account_id)
            auth_key = f"account-{account_id}"
            callback = on_status or (lambda _state, _message: None)
            try:
                result = await asyncio.wait_for(
                    self.auth.authorize(
                        auth_key,
                        expected_vk_user_id=expected_vk_id,
                        on_status=callback,
                        confirmation_event=None,
                    ),
                    timeout=max(float(timeout_seconds), 1.0),
                )
                encrypted, fingerprint = self.pending.take(auth_key)
                self._persist_authorization(
                    result,
                    encrypted,
                    fingerprint,
                    existing_account_id=account_id,
                )
                return self.get_token(account_id)
            except Exception as exc:
                self.pending.pending.pop(auth_key, None)
                self._mark_requires_login(account_id, str(exc))
                raise
            finally:
                self._auth_accounts.discard(account_id)

    async def run_vk(
        self,
        account_id: int,
        operation: Callable[[Any], Awaitable[T]],
        *,
        client_factory: Callable[[str], Any] = VkApiClient,
    ) -> T:
        """Run one VK operation and transparently retry once after an auth-token rejection."""

        async def invoke(token: str) -> T:
            client = client_factory(token)
            try:
                return await operation(client)
            finally:
                token = ""
                await client.aclose()

        token = self.get_token(account_id)
        result = await invoke(token)
        if not self._result_requires_auth(result):
            token = ""
            return result

        failed_token = token
        token = ""
        try:
            fresh_token = await self.refresh_token(account_id, failed_token=failed_token)
        except Exception:
            failed_token = ""
            return result
        try:
            return await invoke(fresh_token)
        finally:
            fresh_token = ""
            failed_token = ""

    @classmethod
    def _result_requires_auth(cls, value: Any) -> bool:
        if isinstance(value, VkActionResult):
            return value.state is AttemptState.AUTH_REQUIRED
        if isinstance(value, (tuple, list)):
            return any(cls._result_requires_auth(item) for item in value)
        return False

    def _mark_requires_login(self, account_id: int, error: str) -> None:
        with Session(self.engine) as session:
            account = session.get(Account, account_id)
            if account is None:
                return
            account.auth_status = "requires_login"
            account.health_status = "requires_login"
            account.health_checked_at = datetime.utcnow()
            account.health_detail = error[:2000]
            account.last_checked_at = datetime.utcnow()
            account.last_error = error[:2000]
            session.commit()

    def update_account(self, account_id: int, *, note: str | None = None, enabled: bool | None = None) -> dict:
        with Session(self.engine) as session:
            account = session.get(Account, account_id)
            if account is None:
                raise KeyError(account_id)
            if note is not None:
                account.note = note.strip()[:250]
            if enabled is not None:
                account.enabled = enabled
            session.commit()
            session.refresh(account)
            profile = session.scalar(select(AccountSecret.browser_profile).where(AccountSecret.account_id == account.id))
            return self._public_account(account, session_ok=bool(profile) and Path(profile).exists())

    def delete_account(self, account_id: int) -> bool:
        if account_id in self._open_accounts:
            raise ValueError("Сначала закройте окно сообщений этого аккаунта")
        if account_id in self._auth_accounts:
            raise ValueError("Сначала завершите авторизацию этого аккаунта")
        with Session(self.engine) as session:
            account = session.get(Account, account_id)
            if account is None:
                return False
            secret = session.scalar(select(AccountSecret).where(AccountSecret.account_id == account_id))
            profile_path = Path(secret.browser_profile).resolve() if secret and secret.browser_profile else None
            session.delete(account)
            session.commit()
        if profile_path and self.profiles_root in profile_path.parents and profile_path.exists():
            shutil.rmtree(profile_path)
        return True

    @staticmethod
    def _public_account(
        account: Account,
        *,
        assigned_groups: int = 0,
        session_ok: bool = False,
        unread_dialogs: int | None = None,
    ) -> dict[str, Any]:
        return {
            "id": account.id,
            "vk_user_id": account.vk_user_id,
            "first_name": account.first_name,
            "last_name": account.last_name,
            "display_name": account.display_name,
            "profile_url": account.profile_url,
            "avatar_url": account.avatar_url,
            "note": account.note,
            "enabled": account.enabled,
            "auth_status": account.auth_status,
            "api_status": "ok" if account.auth_status == "ok" else "error",
            "session_status": "ok" if session_ok else "error",
            "work_status": account.work_status,
            "health_status": account.health_status,
            "health_checked_at": account.health_checked_at.isoformat() if account.health_checked_at else None,
            "health_detail": account.health_detail,
            "assigned_groups": assigned_groups,
            "processed_count": account.processed_count,
            "success_count": account.success_count,
            "failed_count": account.failed_count,
            "unread_count": account.unread_count if unread_dialogs is None else unread_dialogs,
            "last_checked_at": account.last_checked_at.isoformat() if account.last_checked_at else None,
            "last_action_at": account.last_action_at.isoformat() if account.last_action_at else None,
            "last_error": account.last_error,
        }
