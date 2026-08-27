from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.core.enums import WorkItemState
from app.db.models import Account, Community, EventLog, Result, Run, SendAttempt, WorkItem
from app.services.accounts import AccountService
from app.services.normalization import extract_vk_community_refs
from app.vk.client import VkApiClient, VkCommunity


@dataclass(frozen=True, slots=True)
class ImportSummary:
    found: int
    added: int
    duplicates: int
    unresolved: list[str]
    replaced: int = 0

    def public(self) -> dict:
        return asdict(self)


class WorkListService:
    OPEN_RUN_STATES = ("draft", "running", "paused", "stopped", "waiting_limit", "needs_attention", "requires_login")
    IMPORT_MODES = {"append", "replace_waiting"}

    def __init__(self, engine: Engine, accounts: AccountService):
        self.engine = engine
        self.accounts = accounts

    async def import_text(self, raw_text: str, *, mode: str = "append") -> ImportSummary:
        if mode not in self.IMPORT_MODES:
            raise ValueError("Неизвестный режим добавления списка")

        refs = extract_vk_community_refs(raw_text)
        if not refs:
            return ImportSummary(0, 0, 0, [], 0)

        resolved: dict[str, VkCommunity] = {}
        unresolved: list[str] = []
        account_id = self._first_authorized_account_id()
        if account_id is not None:
            runner = getattr(self.accounts, "run_vk", None)
            if callable(runner):
                groups, error = await runner(
                    account_id,
                    lambda client: client.resolve_communities([item.lookup for item in refs]),
                    client_factory=VkApiClient,
                )
            else:
                token = self.accounts.get_token(account_id)
                client = VkApiClient(token)
                try:
                    groups, error = await client.resolve_communities([item.lookup for item in refs])
                finally:
                    token = ""
                    await client.aclose()
            if error is None:
                by_id = {str(item.vk_id): item for item in groups}
                by_screen = {item.screen_name.casefold(): item for item in groups}
                for ref in refs:
                    match = by_id.get(ref.lookup) or by_screen.get(ref.lookup.casefold())
                    if match:
                        resolved[ref.lookup.casefold()] = match

        for ref in refs:
            if ref.lookup.casefold() in resolved:
                continue
            if ref.lookup.isdigit():
                vk_id = int(ref.lookup)
                resolved[ref.lookup.casefold()] = VkCommunity(
                    vk_id=vk_id,
                    screen_name=f"club{vk_id}",
                    name="",
                    canonical_url=f"https://vk.com/club{vk_id}",
                )
            else:
                unresolved.append(ref.lookup)

        added = 0
        duplicates = 0
        replaced = 0
        with Session(self.engine) as session:
            run = session.scalar(
                select(Run).where(Run.state.in_(self.OPEN_RUN_STATES)).order_by(Run.id.desc()).limit(1)
            )
            if run is None:
                run = Run(state="draft")
                session.add(run)
                session.flush()

            if mode == "replace_waiting":
                old_tail = list(
                    session.scalars(
                        select(WorkItem).where(
                            WorkItem.run_id == run.id,
                            WorkItem.state.in_((
                                WorkItemState.WAITING,
                                WorkItemState.ASSIGNED,
                                WorkItemState.PAUSED,
                            )),
                            WorkItem.started_at.is_(None),
                        )
                    ).all()
                )
                replaced = len(old_tail)
                for item in old_tail:
                    session.delete(item)
                session.flush()

            # Deduplication is only inside this logical run/import. Historical
            # runs are deliberately ignored: they are reporting, not a blacklist.
            for ref in refs:
                group = resolved.get(ref.lookup.casefold())
                if group is None:
                    continue
                community = session.scalar(select(Community).where(Community.vk_id == group.vk_id))
                if community is None:
                    community = Community(
                        vk_id=group.vk_id,
                        screen_name=group.screen_name,
                        name=group.name,
                        canonical_url=group.canonical_url,
                        avatar_url=group.avatar_url,
                    )
                    session.add(community)
                    session.flush()
                else:
                    community.screen_name = group.screen_name or community.screen_name
                    community.name = group.name or community.name
                    community.canonical_url = group.canonical_url
                    community.avatar_url = group.avatar_url or community.avatar_url

                existing = session.scalar(
                    select(WorkItem.id).where(
                        WorkItem.run_id == run.id,
                        WorkItem.community_id == community.id,
                    )
                )
                if existing:
                    duplicates += 1
                    continue
                session.add(
                    WorkItem(
                        run_id=run.id,
                        community_id=community.id,
                        original_input=ref.raw,
                        state=WorkItemState.WAITING,
                    )
                )
                session.flush()
                added += 1
            session.commit()
        return ImportSummary(len(refs), added, duplicates, unresolved, replaced)

    def list_active(self, *, limit: int = 500, offset: int = 0) -> dict:
        active_states = (
            WorkItemState.WAITING,
            WorkItemState.ASSIGNED,
            WorkItemState.PROCESSING,
            WorkItemState.RETRY_WAIT,
            WorkItemState.RECONCILE_REQUIRED,
            WorkItemState.PAUSED,
        )
        with Session(self.engine) as session:
            total = session.scalar(
                select(func.count()).select_from(WorkItem).where(WorkItem.state.in_(active_states))
            ) or 0
            rows = session.execute(
                select(WorkItem, Community, Account)
                .join(Community, WorkItem.community_id == Community.id)
                .outerjoin(Account, WorkItem.assigned_account_id == Account.id)
                .where(WorkItem.state.in_(active_states))
                .order_by(WorkItem.id)
                .offset(max(offset, 0))
                .limit(min(max(limit, 1), 2000))
            ).all()
            return {
                "total": total,
                "items": [
                    {
                        "id": item.id,
                        "group_name": community.name or community.screen_name,
                        "url": community.canonical_url,
                        "state": item.state.value,
                        "account": account.display_name if account else "Не назначен",
                        "attempts": item.attempts_count,
                        "last_error": item.last_error,
                    }
                    for item, community, account in rows
                ],
            }

    def remove_unstarted(self, item_ids: list[int]) -> int:
        """Remove selected safe items, including manually dismissed reconcile-required rows.

        A reconcile-required item has already crossed the attempt boundary, so deleting
        it must not refund the account quota.  Quota state is stored separately and is
        intentionally left untouched.  Actively processing/retry-wait items are never
        deleted here.
        """
        if not item_ids:
            return 0
        removable_unstarted = {
            WorkItemState.WAITING,
            WorkItemState.ASSIGNED,
            WorkItemState.PAUSED,
        }
        with Session(self.engine) as session:
            rows = list(session.scalars(
                select(WorkItem).where(WorkItem.id.in_(item_ids))
            ).all())
            removed = 0
            for row in rows:
                safe_unstarted = row.state in removable_unstarted and row.started_at is None
                manual_reconcile = row.state == WorkItemState.RECONCILE_REQUIRED
                if not (safe_unstarted or manual_reconcile):
                    continue
                session.delete(row)
                removed += 1
            session.commit()
            return removed

    def history(self, item_id: int) -> dict:
        with Session(self.engine) as session:
            row = session.execute(
                select(WorkItem, Community, Account)
                .join(Community, WorkItem.community_id == Community.id)
                .outerjoin(Account, WorkItem.assigned_account_id == Account.id)
                .where(WorkItem.id == item_id)
            ).first()
            if row is None:
                raise KeyError(item_id)
            item, community, account = row
            result = session.scalar(select(Result).where(Result.work_item_id == item_id))
            attempts = session.scalars(
                select(SendAttempt).where(SendAttempt.work_item_id == item_id).order_by(SendAttempt.id)
            ).all()
            events = session.scalars(
                select(EventLog).where(EventLog.work_item_id == item_id).order_by(EventLog.id)
            ).all()

            def decode(raw: str) -> dict:
                try:
                    value = json.loads(raw or "{}")
                    return value if isinstance(value, dict) else {"value": value}
                except (TypeError, ValueError):
                    return {"raw": raw}

            return {
                "id": item.id,
                "run_id": item.run_id,
                "group_name": community.name or community.screen_name,
                "url": community.canonical_url,
                "vk_id": community.vk_id,
                "state": item.state.value,
                "account": account.display_name if account else item.account_note_snapshot,
                "attempts_count": item.attempts_count,
                "started_at": item.started_at.isoformat() if item.started_at else None,
                "completed_at": item.completed_at.isoformat() if item.completed_at else None,
                "last_error": item.last_error,
                "result": None if result is None else {
                    "message_state": result.message_state.value,
                    "message_reason": result.message_reason,
                    "suggested_state": result.suggested_state.value,
                    "suggested_reason": result.suggested_reason,
                    "outcome": result.outcome.value,
                    "destination": result.destination,
                },
                "attempts": [
                    {
                        "id": attempt.id,
                        "direction": attempt.direction,
                        "state": attempt.state.value,
                        "vk_object_id": attempt.vk_object_id,
                        "error_code": attempt.error_code,
                        "error_class": attempt.error_class,
                        "reason": attempt.reason,
                        "technical": decode(attempt.diagnostic_json),
                        "created_at": attempt.created_at.isoformat(),
                    }
                    for attempt in attempts
                ],
                "events": [
                    {
                        "id": event.id,
                        "created_at": event.created_at.isoformat(),
                        "level": event.level,
                        "message": event.user_message,
                        "technical": decode(event.technical_json),
                    }
                    for event in events
                ],
            }

    def _first_authorized_account_id(self) -> int | None:
        with Session(self.engine) as session:
            return session.scalar(
                select(Account.id)
                .where(Account.enabled.is_(True), Account.auth_status == "ok")
                .order_by(Account.id)
                .limit(1)
            )
