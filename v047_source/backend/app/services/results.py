from __future__ import annotations

from sqlalchemy import Engine, func, or_, select
from sqlalchemy.orm import Session

from app.core.enums import FinalOutcome
from app.db.models import Account, Community, Result, Run, WorkItem
from app.services.exporting import ResultExportRow, links_text, rows_csv, rows_tsv, rows_xlsx


class ResultsService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def _resolve_run_id(self, session: Session, run_id: int | None) -> int | None:
        if run_id is not None:
            return run_id
        return session.scalar(select(Run.id).order_by(Run.id.desc()).limit(1))

    def list(
        self,
        outcome: FinalOutcome,
        *,
        run_id: int | None = None,
        search: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> dict:
        if outcome not in {FinalOutcome.SUCCESS, FinalOutcome.FAILED}:
            raise ValueError("Доступны только окончательные результаты")
        with Session(self.engine) as session:
            resolved_run_id = self._resolve_run_id(session, run_id)
            if resolved_run_id is None:
                return {"total": 0, "items": []}
            filters = [Result.outcome == outcome, WorkItem.run_id == resolved_run_id]
            if search.strip():
                term = f"%{search.strip()}%"
                filters.append(
                    or_(
                        Community.name.ilike(term),
                        Community.screen_name.ilike(term),
                        Community.canonical_url.ilike(term),
                        Account.note.ilike(term),
                        Account.first_name.ilike(term),
                    )
                )
            base = (
                select(Result, WorkItem, Community, Account)
                .join(WorkItem, Result.work_item_id == WorkItem.id)
                .join(Community, WorkItem.community_id == Community.id)
                .outerjoin(Account, Result.account_id == Account.id)
                .where(*filters)
            )
            total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
            rows = session.execute(
                base.order_by(Result.completed_at.desc(), Result.id.desc())
                .offset(max(offset, 0))
                .limit(min(max(limit, 1), 2000))
            ).all()
            return {"total": total, "items": [self._public(*row) for row in rows]}

    def export_rows(
        self,
        outcome: FinalOutcome,
        selected_ids: list[int] | None = None,
        *,
        run_id: int | None = None,
    ) -> list[ResultExportRow]:
        if outcome not in {FinalOutcome.SUCCESS, FinalOutcome.FAILED}:
            raise ValueError("Доступны только окончательные результаты")
        with Session(self.engine) as session:
            resolved_run_id = self._resolve_run_id(session, run_id)
            if resolved_run_id is None:
                return []
            filters = [Result.outcome == outcome, WorkItem.run_id == resolved_run_id]
            if selected_ids is not None:
                filters.append(Result.id.in_(selected_ids or [-1]))
            rows = session.execute(
                select(Result, WorkItem, Community, Account)
                .join(WorkItem, Result.work_item_id == WorkItem.id)
                .join(Community, WorkItem.community_id == Community.id)
                .outerjoin(Account, Result.account_id == Account.id)
                .where(*filters)
                .order_by(Result.completed_at.desc(), Result.id.desc())
            ).all()
            return [
                ResultExportRow(
                    community.name or community.screen_name,
                    community.canonical_url,
                    "Отправлено" if result.message_state.value == "sent" else "Не отправлено",
                    "Отправлено" if result.suggested_state.value == "sent" else "Не отправлено",
                    result.destination,
                    account.display_name if account else item.account_note_snapshot,
                    "; ".join(value for value in (result.message_reason, result.suggested_reason) if value),
                )
                for result, item, community, account in rows
            ]

    def export(
        self,
        outcome: FinalOutcome,
        mode: str,
        selected_ids: list[int] | None = None,
        *,
        run_id: int | None = None,
    ) -> tuple[bytes, str]:
        rows = self.export_rows(outcome, selected_ids, run_id=run_id)
        if mode == "links":
            return links_text(rows).encode("utf-8"), "text/plain; charset=utf-8"
        if mode == "tsv":
            return rows_tsv(rows).encode("utf-8-sig"), "text/tab-separated-values; charset=utf-8"
        if mode == "csv":
            return rows_csv(rows), "text/csv; charset=utf-8"
        if mode == "xlsx":
            return rows_xlsx(rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        raise ValueError("Неизвестный формат экспорта")

    @staticmethod
    def _public(result: Result, item: WorkItem, community: Community, account: Account | None) -> dict:
        return {
            "id": result.id,
            "work_item_id": item.id,
            "run_id": item.run_id,
            "group_name": community.name or community.screen_name,
            "url": community.canonical_url,
            "message_state": result.message_state.value,
            "message_reason": result.message_reason,
            "suggested_state": result.suggested_state.value,
            "suggested_reason": result.suggested_reason,
            "destination": result.destination,
            "account": account.display_name if account else item.account_note_snapshot,
            "completed_at": result.completed_at.isoformat() if result.completed_at else None,
        }
