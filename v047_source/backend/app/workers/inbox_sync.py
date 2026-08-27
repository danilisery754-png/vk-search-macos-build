from __future__ import annotations

import asyncio
from contextlib import suppress

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db.models import Account


class InboxSyncWorker:
    """Фоновая синхронизация входящих, независимая от очереди рассылки."""

    def __init__(self, engine: Engine, inbox, settings, logs):
        self.engine = engine
        self.inbox = inbox
        self.settings = settings
        self.logs = logs
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._last_sync_error_by_account: dict[int, str] = {}

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping.clear()
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    @staticmethod
    def _error_text(result: dict) -> str:
        raw = str(result.get("error") or "").strip()
        if raw:
            return raw
        state = str(result.get("state") or "").strip()
        if state == "auth_required":
            return "VK требует повторную авторизацию аккаунта"
        if state == "temporary_error":
            return "временная ошибка VK или сети"
        return "VK не вернул описание ошибки синхронизации"

    def _record_sync_failure(self, account_id: int, detail: str) -> None:
        clean = str(detail or "").strip() or "VK не вернул описание ошибки синхронизации"
        previous = self._last_sync_error_by_account.get(account_id)
        if previous != clean:
            self.logs.add(
                f"Не удалось синхронизировать сообщения: {clean}",
                level="warning",
                account_id=account_id,
            )
        self._last_sync_error_by_account[account_id] = clean

    def _record_sync_success(self, account_id: int) -> None:
        if self._last_sync_error_by_account.pop(account_id, None) is not None:
            self.logs.add(
                "Синхронизация сообщений восстановлена",
                level="info",
                account_id=account_id,
            )

    async def sync_once(self) -> dict[str, int]:
        with Session(self.engine) as session:
            account_ids = list(session.scalars(
                select(Account.id)
                .where(Account.enabled.is_(True), Account.auth_status == "ok")
                .order_by(Account.id)
            ).all())
        active_ids = set(account_ids)
        for stale_id in list(self._last_sync_error_by_account):
            if stale_id not in active_ids:
                self._last_sync_error_by_account.pop(stale_id, None)

        succeeded = failed = 0
        for account_id in account_ids:
            try:
                result = await self.inbox.sync_account(account_id)
                if result.get("ok"):
                    succeeded += 1
                    self._record_sync_success(account_id)
                else:
                    failed += 1
                    self._record_sync_failure(account_id, self._error_text(result))
            except Exception as exc:
                failed += 1
                detail = str(exc).strip() or type(exc).__name__
                self._record_sync_failure(account_id, detail)
        return {
            "attempted": len(account_ids),
            "succeeded": succeeded,
            "failed": failed,
            "dialogs": 0,
        }

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            await self.sync_once()
            interval = float(self.settings.all().get("inbox_sync_seconds", 30))
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=max(interval, 5.0))
            except asyncio.TimeoutError:
                pass
