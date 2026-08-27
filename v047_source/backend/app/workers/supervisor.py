from __future__ import annotations

import asyncio
import random
import socket
from contextlib import suppress

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db.models import Account, Run


class WorkerSupervisor:
    def __init__(self, engine: Engine, processor, settings, runs, logs):
        self.engine = engine
        self.processor = processor
        self.settings = settings
        self.runs = runs
        self.logs = logs
        self._main_task: asyncio.Task | None = None
        self._workers: dict[int, asyncio.Task] = {}
        self._stopping = asyncio.Event()
        self.instance_id = f"{socket.gethostname()}-{id(self):x}"

    def start(self) -> None:
        if self._main_task is None or self._main_task.done():
            self._stopping.clear()
            self._main_task = asyncio.create_task(self._supervise())

    async def stop(self) -> None:
        self._stopping.set()
        tasks = list(self._workers.values())
        for task in tasks:
            task.cancel()
        if self._main_task:
            self._main_task.cancel()
        for task in [*tasks, self._main_task]:
            if task:
                with suppress(asyncio.CancelledError):
                    await task
        self._workers.clear()
        self._main_task = None

    async def _supervise(self) -> None:
        while not self._stopping.is_set():
            # The supervisor is intentionally passive: only an explicit API
            # Start/Resume action may transition a run to ``running``.
            with Session(self.engine) as session:
                run = session.scalar(select(Run).where(Run.state == "running").order_by(Run.id.desc()).limit(1))
                active_ids = set(
                    session.scalars(
                        select(Account.id).where(Account.enabled.is_(True), Account.auth_status == "ok")
                    ).all()
                ) if run else set()
                run_id = run.id if run else None

            for account_id in active_ids:
                task = self._workers.get(account_id)
                if task is None or task.done():
                    self._workers[account_id] = asyncio.create_task(self._account_loop(account_id))
            for account_id in set(self._workers) - active_ids:
                task = self._workers.pop(account_id)
                task.cancel()
            if run_id:
                self.runs.finish_if_idle(run_id)
            await asyncio.sleep(0.75)

    async def _account_loop(self, account_id: int) -> None:
        owner = f"{self.instance_id}:account:{account_id}"
        self._set_account_status(account_id, "working", "")
        try:
            while not self._stopping.is_set():
                with Session(self.engine) as session:
                    run_state = session.scalar(select(Run.state).order_by(Run.id.desc()).limit(1))
                    account = session.get(Account, account_id)
                    allowed = bool(account and account.enabled and account.auth_status == "ok")
                if not allowed or run_state != "running":
                    return
                try:
                    worked = await self.processor.process_next(account_id, owner)
                except Exception as exc:
                    self.logs.add(
                        f"Аккаунт временно остановлен из-за ошибки: {exc}",
                        level="error",
                        account_id=account_id,
                    )
                    self._set_account_status(account_id, "error", str(exc))
                    await asyncio.sleep(5)
                    continue
                if not worked:
                    await asyncio.sleep(1)
                    continue
                await asyncio.sleep(self._delay())
        finally:
            self._set_account_status(account_id, "stopped", "")

    def _delay(self) -> float:
        values = self.settings.all()
        if values.get("delay_mode") == "random":
            low = float(values.get("delay_min_seconds", 60))
            high = float(values.get("delay_max_seconds", low))
            return random.uniform(min(low, high), max(low, high))
        return float(values.get("delay_seconds", 60))

    def _set_account_status(self, account_id: int, status: str, error: str) -> None:
        with Session(self.engine) as session:
            account = session.get(Account, account_id)
            if account:
                account.work_status = status
                if error:
                    account.last_error = error
                session.commit()

