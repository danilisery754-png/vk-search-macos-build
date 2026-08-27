from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import WorkItemState
from app.db.models import Account, AccountSecret, Dialog, WorkItem
from app.services.accounts import AccountService as BaseAccountService


class AccountService(BaseAccountService):
    """v0.4.9 account projections layered on the stable account service.

    Archive is a local inbox state. It must not change account identity, quota,
    authorization, sender assignment, or any other account behavior. The only
    runtime difference here is the public unread-dialog counter: archived
    dialogs are excluded while preserving the v0.4.8 'count dialogs, not
    messages' semantic.
    """

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
                .where(
                    Dialog.unread_count > 0,
                    Dialog.is_archived.is_(False),
                )
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
