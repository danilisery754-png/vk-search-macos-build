from __future__ import annotations

from datetime import timezone

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.core.enums import FinalOutcome, WorkItemState
from app.db.models import Account, Dialog, EventLog, Result, Run, WorkItem


class DashboardService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def snapshot(self) -> dict:
        active_states = (
            WorkItemState.WAITING,
            WorkItemState.ASSIGNED,
            WorkItemState.PROCESSING,
            WorkItemState.RETRY_WAIT,
            WorkItemState.RECONCILE_REQUIRED,
            WorkItemState.PAUSED,
        )
        with Session(self.engine) as session:
            run = session.scalar(select(Run).order_by(Run.id.desc()).limit(1))
            metrics = {
                "active_accounts": session.scalar(
                    select(func.count()).select_from(Account).where(Account.enabled.is_(True), Account.auth_status == "ok")
                ) or 0,
                "remaining": session.scalar(
                    select(func.count()).select_from(WorkItem).where(WorkItem.state.in_(active_states))
                ) or 0,
                "processing": session.scalar(
                    select(func.count()).select_from(WorkItem).where(WorkItem.state == WorkItemState.PROCESSING)
                ) or 0,
                "success": session.scalar(
                    select(func.count()).select_from(Result).where(Result.outcome == FinalOutcome.SUCCESS)
                ) or 0,
                "failed": session.scalar(
                    select(func.count()).select_from(Result).where(Result.outcome == FinalOutcome.FAILED)
                ) or 0,
                "unread": session.scalar(
                    select(func.count()).select_from(Dialog).where(
                        Dialog.unread_count > 0,
                        Dialog.is_archived.is_(False),
                    )
                ) or 0,
            }
            events = session.scalars(select(EventLog).order_by(EventLog.id.desc()).limit(20)).all()
            return {
                "work_state": run.state if run else "empty",
                "metrics": metrics,
                "events": [
                    {
                        "id": event.id,
                        "time": event.created_at.replace(tzinfo=timezone.utc).isoformat(),
                        "level": event.level,
                        "message": event.user_message,
                    }
                    for event in events
                ],
            }
