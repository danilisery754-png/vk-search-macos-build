from __future__ import annotations

from datetime import datetime

from sqlalchemy import Engine, case, delete, func, select, update
from sqlalchemy.orm import Session

from app.core.enums import FinalOutcome, WorkItemState
from app.db.models import Account, EventLog, Result, Run, SendAttempt, WorkItem
from app.services.quota import QuotaService
from app.services.settings import SettingsService


class RunService:
    ACTIVE_OR_RESUMABLE_STATES = ("draft", "paused", "stopped", "waiting_limit", "needs_attention", "requires_login")

    def __init__(self, engine: Engine, settings: SettingsService):
        self.engine = engine
        self.settings = settings
        self.quota = QuotaService(engine, settings)

    def suspend_unconfirmed_on_startup(self) -> int:
        """Require an explicit user Start/Resume after every desktop restart.

        A previous process may have died while a run was marked ``running`` or
        ``waiting_limit``.  Those persisted states are *not* user consent to send
        messages in a new application session.
        """
        with Session(self.engine) as session:
            rows = list(session.scalars(
                select(Run).where(Run.state.in_(("running", "waiting_limit")))
            ).all())
            for run in rows:
                run.state = "paused"
            if rows:
                session.commit()
            return len(rows)

    def start(self, *, ignore_limits: bool = False) -> dict:
        with Session(self.engine) as session:
            running = session.scalar(select(Run).where(Run.state == "running").order_by(Run.id.desc()).limit(1))
            if running:
                account_ids = self._active_account_ids(session)
                if ignore_limits:
                    self.quota.reset(account_ids)
                return {
                    "run_id": running.id,
                    "state": running.state,
                    "already_running": True,
                    "quota_reset": bool(ignore_limits),
                }

            run = session.scalar(
                select(Run)
                .where(Run.state.in_(self.ACTIVE_OR_RESUMABLE_STATES))
                .order_by(Run.id.desc())
                .limit(1)
            )
            if run is None:
                raise ValueError("Список групп пуст")

            accounts = list(
                session.scalars(
                    select(Account)
                    .where(Account.enabled.is_(True), Account.auth_status == "ok")
                    .order_by(Account.id)
                ).all()
            )
            if not accounts:
                raise ValueError("Сначала подключите хотя бы один активный VK-аккаунт")
            account_ids = [account.id for account in accounts]

            if ignore_limits:
                self.quota.reset(account_ids)
            elif run.state == "waiting_limit" and not self.quota.any_available(account_ids):
                unlock = self.quota.next_unlock(account_ids)
                return {
                    "run_id": run.id,
                    "state": "waiting_limit",
                    "already_running": True,
                    "quota_reset": False,
                    "next_unlock_at": unlock.isoformat() if unlock else None,
                }

            if run.started_at is None and run.original_count == 0:
                run.original_count = session.scalar(
                    select(func.count()).select_from(WorkItem).where(WorkItem.run_id == run.id)
                ) or 0

            # v0.4.1 never pre-assigns the whole list. Any old item that was
            # assigned but never started is returned to the shared waiting pool.
            for item in session.scalars(
                select(WorkItem).where(
                    WorkItem.run_id == run.id,
                    WorkItem.state == WorkItemState.ASSIGNED,
                    WorkItem.started_at.is_(None),
                )
            ):
                item.state = WorkItemState.WAITING
                item.assigned_account_id = None
                item.account_note_snapshot = ""

            if run.state == "stopped":
                active_account_ids = set(account_ids)
                for item in session.scalars(
                    select(WorkItem).where(
                        WorkItem.run_id == run.id,
                        WorkItem.state == WorkItemState.PAUSED,
                    )
                ):
                    if item.started_at is None:
                        item.state = WorkItemState.WAITING
                        item.assigned_account_id = None
                        item.account_note_snapshot = ""
                    elif item.assigned_account_id in active_account_ids:
                        # Already-started work remains bound to the same account so
                        # retries cannot silently become a duplicate from another account.
                        item.state = WorkItemState.ASSIGNED

            waiting = session.scalar(
                select(func.count()).select_from(WorkItem).where(
                    WorkItem.run_id == run.id,
                    WorkItem.state == WorkItemState.WAITING,
                )
            ) or 0
            run.state = "running"
            run.started_at = run.started_at or datetime.utcnow()
            run.stopped_at = None
            session.commit()
            return {
                "run_id": run.id,
                "state": run.state,
                "assigned": 0,
                "left_unassigned": int(waiting),
                "already_running": False,
                "quota_reset": bool(ignore_limits),
            }

    def pause(self) -> dict:
        with Session(self.engine) as session:
            run = session.scalar(
                select(Run).where(Run.state.in_(("running", "waiting_limit"))).order_by(Run.id.desc()).limit(1)
            )
            if run is None:
                return {"changed": False, "state": self.current_state()["state"]}
            run.state = "paused"
            session.commit()
            return {"changed": True, "run_id": run.id, "state": "paused"}

    def resume(self) -> dict:
        # Resume is deliberately as capable as Start: legacy needs_attention and
        # requires_login runs can recover once safe waiting work/accounts exist.
        return self.start(ignore_limits=False)

    def stop(self) -> dict:
        with Session(self.engine) as session:
            run = session.scalar(
                select(Run)
                .where(Run.state.in_(("running", "paused", "waiting_limit", "needs_attention", "requires_login")))
                .order_by(Run.id.desc())
            )
            if run is None:
                return {"changed": False, "state": "stopped"}
            run.state = "stopped"
            run.stopped_at = datetime.utcnow()
            for item in session.scalars(
                select(WorkItem).where(
                    WorkItem.run_id == run.id,
                    WorkItem.state.in_((WorkItemState.WAITING, WorkItemState.ASSIGNED, WorkItemState.PAUSED)),
                    WorkItem.started_at.is_(None),
                )
            ):
                item.state = WorkItemState.PAUSED
            session.commit()
            return {"changed": True, "run_id": run.id, "state": run.state}

    def try_resume_waiting(self, *, now: datetime | None = None) -> dict | None:
        moment = now or datetime.utcnow()
        with Session(self.engine) as session:
            run = session.scalar(
                select(Run).where(Run.state == "waiting_limit").order_by(Run.id.desc()).limit(1)
            )
            if run is None:
                return None
            account_ids = self._active_account_ids(session)
            if not account_ids or not self.quota.any_available(account_ids, now=moment):
                return None
            run.state = "running"
            session.commit()
            return {"run_id": run.id, "state": "running", "resumed_from_limit": True}

    def next_unlock_at(self, *, now: datetime | None = None) -> datetime | None:
        moment = now or datetime.utcnow()
        with Session(self.engine) as session:
            run = session.scalar(
                select(Run).where(Run.state == "waiting_limit").order_by(Run.id.desc()).limit(1)
            )
            if run is None:
                return None
            account_ids = self._active_account_ids(session)
        return self.quota.next_unlock(account_ids, now=moment) if account_ids else None

    def list_history(self) -> dict:
        with Session(self.engine) as session:
            work_counts = (
                select(
                    WorkItem.run_id.label("run_id"),
                    func.count(WorkItem.id).label("work_count"),
                    func.sum(
                        case(
                            (WorkItem.state.in_((WorkItemState.SUCCESS, WorkItemState.FAILED)), 1),
                            else_=0,
                        )
                    ).label("processed_count"),
                )
                .group_by(WorkItem.run_id)
                .subquery()
            )
            result_counts = (
                select(
                    WorkItem.run_id.label("run_id"),
                    func.sum(case((Result.outcome == FinalOutcome.SUCCESS, 1), else_=0)).label("success_count"),
                    func.sum(case((Result.outcome == FinalOutcome.FAILED, 1), else_=0)).label("failure_count"),
                )
                .join(Result, Result.work_item_id == WorkItem.id)
                .group_by(WorkItem.run_id)
                .subquery()
            )
            rows = session.execute(
                select(
                    Run,
                    work_counts.c.work_count,
                    work_counts.c.processed_count,
                    result_counts.c.success_count,
                    result_counts.c.failure_count,
                )
                .outerjoin(work_counts, work_counts.c.run_id == Run.id)
                .outerjoin(result_counts, result_counts.c.run_id == Run.id)
                .order_by(Run.id.desc())
            ).all()
            items = []
            for run, work_count, processed_count, success_count, failure_count in rows:
                items.append({
                    "id": run.id,
                    "state": run.state,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "original_count": int(run.original_count or work_count or 0),
                    "processed_count": int(processed_count or 0),
                    "success_count": int(success_count or 0),
                    "failure_count": int(failure_count or 0),
                })
            return {"current_run_id": items[0]["id"] if items else None, "items": items}

    def delete_history(self, run_id: int) -> bool:
        with Session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                return False
            current_id = session.scalar(select(Run.id).order_by(Run.id.desc()).limit(1))
            if run.id == current_id:
                raise ValueError("Нельзя удалить текущий запуск")
            item_ids = list(session.scalars(select(WorkItem.id).where(WorkItem.run_id == run.id)).all())
            if item_ids:
                session.execute(
                    update(EventLog).where(EventLog.work_item_id.in_(item_ids)).values(work_item_id=None)
                )
                session.execute(delete(Result).where(Result.work_item_id.in_(item_ids)))
                session.execute(delete(SendAttempt).where(SendAttempt.work_item_id.in_(item_ids)))
                session.execute(delete(WorkItem).where(WorkItem.id.in_(item_ids)))
            session.delete(run)
            session.commit()
            return True

    def current_state(self) -> dict:
        with Session(self.engine) as session:
            run = session.scalar(select(Run).order_by(Run.id.desc()).limit(1))
            state = run.state if run else "empty"
            run_id = run.id if run else None
        result = {"run_id": run_id, "state": state}
        if state == "waiting_limit":
            unlock = self.next_unlock_at()
            result["next_unlock_at"] = unlock.isoformat() if unlock else None
        return result

    def finish_if_idle(self, run_id: int, *, now: datetime | None = None) -> dict | None:
        moment = now or datetime.utcnow()
        with Session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None or run.state != "running":
                return None
            actionable = session.scalar(
                select(func.count())
                .select_from(WorkItem)
                .where(
                    WorkItem.run_id == run_id,
                    WorkItem.state.in_(
                        (WorkItemState.ASSIGNED, WorkItemState.PROCESSING, WorkItemState.RETRY_WAIT)
                    ),
                )
            ) or 0
            if actionable:
                return None
            waiting = session.scalar(
                select(func.count())
                .select_from(WorkItem)
                .where(WorkItem.run_id == run_id, WorkItem.state == WorkItemState.WAITING)
            ) or 0
            blocked = session.scalar(
                select(func.count())
                .select_from(WorkItem)
                .where(
                    WorkItem.run_id == run_id,
                    WorkItem.state.in_((WorkItemState.RECONCILE_REQUIRED, WorkItemState.PAUSED)),
                )
            ) or 0
            # A reconcile-required item is local to that group. It must never
            # freeze other waiting groups. Only surface needs_attention after
            # all safe/actionable work has been drained.
            if waiting:
                account_ids = self._active_account_ids(session)
                if not account_ids:
                    run.state = "requires_login"
                elif self.quota.any_available(account_ids, now=moment):
                    return None
                else:
                    run.state = "waiting_limit"
            elif blocked:
                run.state = "needs_attention"
            else:
                run.state = "completed"
                run.finished_at = moment
            session.commit()
            result = {
                "run_id": run.id,
                "state": run.state,
                "remaining": int(waiting),
                "needs_attention": int(blocked),
            }
            if run.state == "waiting_limit":
                unlock = self.quota.next_unlock(account_ids, now=moment)
                result["next_unlock_at"] = unlock.isoformat() if unlock else None
            return result

    def reconcile_state(self, run_id: int, *, now: datetime | None = None) -> dict:
        """Recalculate an unfinished run after manual item removal."""
        moment = now or datetime.utcnow()
        with Session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise KeyError(run_id)
            remaining = session.scalar(
                select(func.count()).select_from(WorkItem).where(
                    WorkItem.run_id == run_id,
                    WorkItem.state.in_((
                        WorkItemState.WAITING, WorkItemState.ASSIGNED, WorkItemState.PROCESSING,
                        WorkItemState.RETRY_WAIT, WorkItemState.RECONCILE_REQUIRED, WorkItemState.PAUSED,
                    )),
                )
            ) or 0
            waiting = session.scalar(
                select(func.count()).select_from(WorkItem).where(
                    WorkItem.run_id == run_id, WorkItem.state == WorkItemState.WAITING
                )
            ) or 0
            blocked = session.scalar(
                select(func.count()).select_from(WorkItem).where(
                    WorkItem.run_id == run_id,
                    WorkItem.state.in_((WorkItemState.RECONCILE_REQUIRED, WorkItemState.PAUSED)),
                )
            ) or 0
            if not remaining:
                run.state = "completed"
                run.finished_at = moment
            elif waiting:
                account_ids = self._active_account_ids(session)
                if not account_ids:
                    run.state = "requires_login"
                elif self.quota.any_available(account_ids, now=moment):
                    run.state = "running"
                else:
                    run.state = "waiting_limit"
            elif blocked:
                run.state = "needs_attention"
            session.commit()
            return {"run_id": run.id, "state": run.state, "remaining": int(remaining), "needs_attention": int(blocked)}

    def _transition(self, source: str, target: str) -> dict:
        with Session(self.engine) as session:
            run = session.scalar(select(Run).where(Run.state == source).order_by(Run.id.desc()).limit(1))
            if run is None:
                return {"changed": False, "state": self.current_state()["state"]}
            run.state = target
            session.commit()
            return {"changed": True, "run_id": run.id, "state": target}

    @staticmethod
    def _active_account_ids(session: Session) -> list[int]:
        return list(
            session.scalars(
                select(Account.id)
                .where(Account.enabled.is_(True), Account.auth_status == "ok")
                .order_by(Account.id)
            ).all()
        )
