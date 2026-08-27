from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db.models import Account, EventLog
from app.vk.errors import redact_secrets


class EventLogService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def add(
        self,
        message: str,
        *,
        level: str = "info",
        category: str = "system",
        event_type: str = "",
        account_id: int | None = None,
        work_item_id: int | None = None,
        technical: dict[str, Any] | None = None,
    ) -> None:
        safe_technical = redact_secrets(json.dumps(technical or {}, ensure_ascii=False, default=str))
        with Session(self.engine) as session:
            session.add(
                EventLog(
                    level=level,
                    category=category,
                    event_type=event_type,
                    account_id=account_id,
                    work_item_id=work_item_id,
                    user_message=redact_secrets(message),
                    technical_json=safe_technical,
                )
            )
            session.commit()

    def list(
        self,
        *,
        limit: int = 300,
        account_id: int | None = None,
        work_item_id: int | None = None,
        category: str | None = None,
        level: str | None = None,
    ) -> list[dict]:
        query = select(EventLog)
        if account_id is not None:
            query = query.where(EventLog.account_id == account_id)
        if work_item_id is not None:
            query = query.where(EventLog.work_item_id == work_item_id)
        if category and category != "all":
            query = query.where(EventLog.category == category)
        if level and level != "all":
            query = query.where(EventLog.level == level)
        with Session(self.engine) as session:
            rows = session.scalars(query.order_by(EventLog.id.desc()).limit(min(max(limit, 1), 2000))).all()
            account_ids = {int(row.account_id) for row in rows if row.account_id is not None}
            account_names = {
                int(account.id): account.display_name
                for account in session.scalars(select(Account).where(Account.id.in_(account_ids))).all()
            } if account_ids else {}
            return [
                {
                    "id": row.id,
                    "created_at": row.created_at.isoformat(),
                    "level": row.level,
                    "category": row.category,
                    "event_type": row.event_type,
                    "account_id": row.account_id,
                    "work_item_id": row.work_item_id,
                    "account_display_name": account_names.get(int(row.account_id)) if row.account_id is not None else None,
                    "message": row.user_message,
                    "technical": json.loads(row.technical_json or "{}"),
                }
                for row in rows
            ]
