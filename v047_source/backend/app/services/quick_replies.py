from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.db.models import QuickReply


class QuickReplyService:
    def __init__(self, engine: Engine):
        self.engine = engine

    @staticmethod
    def _public(row: QuickReply) -> dict:
        return {
            "id": row.id,
            "text": row.text,
            "position": row.position,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    @staticmethod
    def _normalize(text: str) -> str:
        value = str(text).strip()
        if not value:
            raise ValueError("Текст шаблона не может быть пустым")
        if len(value) > 4096:
            raise ValueError("Текст шаблона не может быть длиннее 4096 символов")
        return value

    def list(self) -> list[dict]:
        with Session(self.engine) as session:
            rows = session.scalars(select(QuickReply).order_by(QuickReply.position, QuickReply.created_at, QuickReply.id)).all()
            return [self._public(row) for row in rows]

    def create(self, text: str) -> dict:
        value = self._normalize(text)
        with Session(self.engine) as session:
            position = int(session.scalar(select(func.max(QuickReply.position))) or -1) + 1
            row = QuickReply(id=uuid.uuid4().hex, text=value, position=position)
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._public(row)

    def update(self, reply_id: str, text: str) -> dict:
        value = self._normalize(text)
        with Session(self.engine) as session:
            row = session.get(QuickReply, reply_id)
            if row is None:
                raise KeyError(reply_id)
            row.text = value
            row.updated_at = datetime.utcnow()
            session.commit()
            session.refresh(row)
            return self._public(row)

    def delete(self, reply_id: str) -> bool:
        with Session(self.engine) as session:
            row = session.get(QuickReply, reply_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True
