from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Engine, text

from app.core.enums import WorkItemState
from app.services.quota import reserve_quota_on_connection


def utc_now() -> datetime:
    return datetime.utcnow()


@dataclass(frozen=True, slots=True)
class ClaimedWorkItem:
    id: int
    run_id: int
    community_id: int
    account_id: int
    attempts_count: int


class QueueRepository:
    """Транзакционная граница очереди.

    Сетевые вызовы никогда не выполняются внутри методов этого класса.
    Для нового v0.4.1 пути выбор свежей группы и расход суточной квоты
    происходят в одной SQLite write-транзакции.
    """

    def __init__(self, engine: Engine):
        self.engine = engine

    def claim_next(
        self,
        account_id: int,
        owner: str,
        *,
        lease_seconds: int = 180,
        daily_limit: int | None = None,
        now: datetime | None = None,
    ) -> ClaimedWorkItem | None:
        moment = now or utc_now()
        lease_until = moment + timedelta(seconds=lease_seconds)
        with self.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                if daily_limit is None:
                    result = self._claim_legacy_assigned(
                        connection,
                        account_id,
                        owner,
                        moment,
                        lease_until,
                    )
                    connection.commit()
                    return result

                # A retry of a group that already consumed one quota unit must be
                # allowed even while the account has no fresh capacity. Otherwise
                # one temporary VK error could deadlock an already-counted item.
                row = connection.execute(
                    text(
                        """
                        SELECT wi.id, wi.run_id, wi.community_id,
                               wi.assigned_account_id, wi.attempts_count,
                               wi.quota_counted_at
                        FROM work_items AS wi
                        JOIN runs AS r ON r.id = wi.run_id
                        WHERE wi.assigned_account_id = :account_id
                          AND wi.quota_counted_at IS NOT NULL
                          AND wi.state IN ('assigned', 'retry_wait')
                          AND (wi.next_retry_at IS NULL OR wi.next_retry_at <= :now)
                          AND r.state IN ('running', 'waiting_limit')
                        ORDER BY r.id DESC, wi.id
                        LIMIT 1
                        """
                    ),
                    {"account_id": account_id, "now": moment},
                ).mappings().first()

                needs_quota = False
                if row is None:
                    # Compatibility/recovery path for work assigned by v0.4.0 but
                    # never actually started. It becomes counted only now.
                    row = connection.execute(
                        text(
                            """
                            SELECT wi.id, wi.run_id, wi.community_id,
                                   wi.assigned_account_id, wi.attempts_count,
                                   wi.quota_counted_at
                            FROM work_items AS wi
                            JOIN runs AS r ON r.id = wi.run_id
                            WHERE wi.assigned_account_id = :account_id
                              AND wi.quota_counted_at IS NULL
                              AND wi.state IN ('assigned', 'retry_wait')
                              AND (wi.next_retry_at IS NULL OR wi.next_retry_at <= :now)
                              AND r.state IN ('running', 'waiting_limit')
                            ORDER BY r.id DESC, wi.id
                            LIMIT 1
                            """
                        ),
                        {"account_id": account_id, "now": moment},
                    ).mappings().first()
                    needs_quota = row is not None

                if row is None:
                    # Normal v0.4.1 path: no permanent upfront assignment. Take
                    # one waiting item only when this account is ready for it.
                    row = connection.execute(
                        text(
                            """
                            SELECT wi.id, wi.run_id, wi.community_id,
                                   wi.assigned_account_id, wi.attempts_count,
                                   wi.quota_counted_at
                            FROM work_items AS wi
                            JOIN runs AS r ON r.id = wi.run_id
                            WHERE wi.state = 'waiting'
                              AND wi.assigned_account_id IS NULL
                              AND r.state IN ('running', 'waiting_limit')
                            ORDER BY r.id DESC, wi.id
                            LIMIT 1
                            """
                        )
                    ).mappings().first()
                    needs_quota = row is not None

                if row is None:
                    connection.commit()
                    return None

                if needs_quota:
                    reserved = reserve_quota_on_connection(
                        connection,
                        account_id,
                        int(daily_limit),
                        now=moment,
                    )
                    if reserved is None:
                        connection.commit()
                        return None

                display_name = self._account_display_name(connection, account_id)
                changed = connection.execute(
                    text(
                        """
                        UPDATE work_items
                        SET state = 'processing',
                            assigned_account_id = :account_id,
                            account_note_snapshot = CASE
                                WHEN account_note_snapshot = '' THEN :display_name
                                ELSE account_note_snapshot
                            END,
                            lease_owner = :owner,
                            lease_expires_at = :lease_until,
                            started_at = COALESCE(started_at, :now),
                            quota_counted_at = COALESCE(quota_counted_at, :quota_counted_at),
                            attempts_count = attempts_count + 1,
                            updated_at = :now
                        WHERE id = :item_id
                          AND state IN ('waiting', 'assigned', 'retry_wait')
                        """
                    ),
                    {
                        "account_id": account_id,
                        "display_name": display_name,
                        "owner": owner,
                        "lease_until": lease_until,
                        "now": moment,
                        "quota_counted_at": moment if needs_quota else row["quota_counted_at"],
                        "item_id": row["id"],
                    },
                )
                if changed.rowcount != 1:
                    connection.rollback()
                    return None

                # If this claim wakes a run whose only reason for waiting was the
                # daily limit, the logical run continues instead of creating a new run.
                connection.execute(
                    text(
                        """
                        UPDATE runs
                        SET state = 'running', updated_at = :now
                        WHERE id = :run_id AND state = 'waiting_limit'
                        """
                    ),
                    {"run_id": row["run_id"], "now": moment},
                )
                connection.commit()
                return ClaimedWorkItem(
                    id=row["id"],
                    run_id=row["run_id"],
                    community_id=row["community_id"],
                    account_id=account_id,
                    attempts_count=row["attempts_count"] + 1,
                )
            except BaseException:
                connection.rollback()
                raise

    @staticmethod
    def _claim_legacy_assigned(connection, account_id: int, owner: str, now: datetime, lease_until: datetime):
        """Preserve the v0.4.0 repository contract for old tests/integrations.

        Production v0.4.1 workers pass ``daily_limit`` and therefore use the
        quota-aware path above.
        """
        row = connection.execute(
            text(
                """
                SELECT id, run_id, community_id, assigned_account_id, attempts_count
                FROM work_items
                WHERE assigned_account_id = :account_id
                  AND state IN ('assigned', 'retry_wait')
                  AND (next_retry_at IS NULL OR next_retry_at <= :now)
                ORDER BY id
                LIMIT 1
                """
            ),
            {"account_id": account_id, "now": now},
        ).mappings().first()
        if row is None:
            return None
        changed = connection.execute(
            text(
                """
                UPDATE work_items
                SET state = 'processing', lease_owner = :owner,
                    lease_expires_at = :lease_until,
                    started_at = COALESCE(started_at, :now),
                    attempts_count = attempts_count + 1,
                    updated_at = :now
                WHERE id = :item_id AND state IN ('assigned', 'retry_wait')
                """
            ),
            {"owner": owner, "lease_until": lease_until, "now": now, "item_id": row["id"]},
        )
        if changed.rowcount != 1:
            return None
        return ClaimedWorkItem(
            id=row["id"],
            run_id=row["run_id"],
            community_id=row["community_id"],
            account_id=row["assigned_account_id"],
            attempts_count=row["attempts_count"] + 1,
        )

    @staticmethod
    def _account_display_name(connection, account_id: int) -> str:
        row = connection.execute(
            text(
                """
                SELECT vk_user_id, first_name, last_name, note
                FROM accounts WHERE id = :account_id
                """
            ),
            {"account_id": account_id},
        ).mappings().first()
        if row is None:
            return f"Аккаунт {account_id}"
        note = (row["note"] or "").strip()
        if note:
            return note
        full_name = f"{row['first_name'] or ''} {row['last_name'] or ''}".strip()
        return full_name or f"Аккаунт {row['vk_user_id']}"

    def recover_expired(self) -> int:
        now = utc_now()
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE work_items
                    SET state = 'reconcile_required', lease_owner = NULL,
                        lease_expires_at = NULL, updated_at = :now,
                        last_error = 'Приложение завершилось во время внешнего действия; требуется безопасная сверка.'
                    WHERE state = 'processing'
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at < :now
                    """
                ),
                {"now": now},
            )
            return result.rowcount

    def release_unstarted(self, account_id: int) -> int:
        now = utc_now()
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE work_items
                    SET state = 'waiting', assigned_account_id = NULL,
                        account_note_snapshot = '',
                        lease_owner = NULL, lease_expires_at = NULL, updated_at = :now
                    WHERE assigned_account_id = :account_id
                      AND state = 'assigned'
                      AND quota_counted_at IS NULL
                    """
                ),
                {"account_id": account_id, "now": now},
            )
            return result.rowcount

    def schedule_retry(self, item_id: int, *, delay_seconds: float, reason: str) -> bool:
        now = utc_now()
        retry_at = now + timedelta(seconds=delay_seconds)
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE work_items
                    SET state = 'retry_wait', next_retry_at = :retry_at,
                        lease_owner = NULL, lease_expires_at = NULL,
                        last_error = :reason, updated_at = :now
                    WHERE id = :item_id AND state = 'processing'
                    """
                ),
                {"item_id": item_id, "retry_at": retry_at, "reason": reason, "now": now},
            )
            return result.rowcount == 1

    def mark_reconcile(self, item_id: int, reason: str) -> bool:
        now = utc_now()
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE work_items
                    SET state = 'reconcile_required', lease_owner = NULL,
                        lease_expires_at = NULL, last_error = :reason, updated_at = :now
                    WHERE id = :item_id AND state = 'processing'
                    """
                ),
                {"item_id": item_id, "reason": reason, "now": now},
            )
            return result.rowcount == 1

    def mark_paused(self, item_id: int, reason: str) -> bool:
        now = utc_now()
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE work_items
                    SET state = 'paused', lease_owner = NULL,
                        lease_expires_at = NULL, last_error = :reason, updated_at = :now
                    WHERE id = :item_id AND state = 'processing'
                    """
                ),
                {"item_id": item_id, "reason": reason, "now": now},
            )
            return result.rowcount == 1

    def finalize(self, item_id: int, state: WorkItemState) -> bool:
        if state not in {WorkItemState.SUCCESS, WorkItemState.FAILED}:
            raise ValueError("Финальный статус должен быть success или failed")
        now = utc_now()
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE work_items
                    SET state = :state, completed_at = :now, next_retry_at = NULL,
                        lease_owner = NULL, lease_expires_at = NULL, updated_at = :now
                    WHERE id = :item_id AND state IN ('processing', 'reconcile_required')
                    """
                ),
                {"item_id": item_id, "state": state.value, "now": now},
            )
            return result.rowcount == 1
