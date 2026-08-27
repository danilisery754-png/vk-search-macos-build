from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Sequence

from sqlalchemy import Connection, Engine, delete, insert, select, update

from app.db.models import AccountQuota


WINDOW = timedelta(hours=24)


def utc_now() -> datetime:
    return datetime.utcnow()


@dataclass(frozen=True, slots=True)
class QuotaSnapshot:
    account_id: int
    limit: int
    consumed: int
    available: int
    window_started_at: datetime | None
    window_ends_at: datetime | None

    @property
    def blocked(self) -> bool:
        return self.available <= 0

    def public(self) -> dict:
        return {
            "daily_limit": self.limit,
            "quota_consumed": self.consumed,
            "quota_available": self.available,
            "quota_window_started_at": self.window_started_at.isoformat() if self.window_started_at else None,
            "quota_window_ends_at": self.window_ends_at.isoformat() if self.window_ends_at else None,
        }


def _logical_snapshot(
    account_id: int,
    limit: int,
    row,
    now: datetime,
) -> QuotaSnapshot:
    limit = max(int(limit), 0)
    if row is None:
        return QuotaSnapshot(account_id, limit, 0, limit, None, None)

    started = row["window_started_at"]
    ends = row["window_ends_at"]
    consumed = max(int(row["consumed"] or 0), 0)
    if ends is None or ends <= now:
        return QuotaSnapshot(account_id, limit, 0, limit, None, None)
    return QuotaSnapshot(
        account_id=account_id,
        limit=limit,
        consumed=consumed,
        available=max(limit - consumed, 0),
        window_started_at=started,
        window_ends_at=ends,
    )


def quota_snapshot_on_connection(
    connection: Connection,
    account_id: int,
    limit: int,
    *,
    now: datetime,
) -> QuotaSnapshot:
    row = connection.execute(
        select(AccountQuota.__table__).where(AccountQuota.account_id == account_id)
    ).mappings().first()
    return _logical_snapshot(account_id, limit, row, now)


def reserve_quota_on_connection(
    connection: Connection,
    account_id: int,
    limit: int,
    *,
    now: datetime,
) -> QuotaSnapshot | None:
    """Consume exactly one unit inside the caller's write transaction.

    The caller must serialize competing writers (SQLite uses BEGIN IMMEDIATE in
    the queue/quota repositories). Expired rows are replaced by a fresh rolling
    24-hour window beginning at ``now``.
    """

    current = quota_snapshot_on_connection(connection, account_id, limit, now=now)
    if current.available <= 0:
        return None

    table = AccountQuota.__table__
    if current.window_ends_at is None:
        started = now
        ends = now + WINDOW
        existing = connection.execute(
            select(table.c.account_id).where(table.c.account_id == account_id)
        ).scalar_one_or_none()
        values = {
            "window_started_at": started,
            "window_ends_at": ends,
            "consumed": 1,
            "updated_at": now,
        }
        if existing is None:
            connection.execute(
                insert(table).values(
                    account_id=account_id,
                    created_at=now,
                    **values,
                )
            )
        else:
            connection.execute(
                update(table).where(table.c.account_id == account_id).values(**values)
            )
        return QuotaSnapshot(account_id, max(int(limit), 0), 1, max(int(limit) - 1, 0), started, ends)

    consumed = current.consumed + 1
    connection.execute(
        update(table)
        .where(table.c.account_id == account_id)
        .values(consumed=consumed, updated_at=now)
    )
    return QuotaSnapshot(
        account_id,
        current.limit,
        consumed,
        max(current.limit - consumed, 0),
        current.window_started_at,
        current.window_ends_at,
    )


class QuotaService:
    def __init__(self, engine: Engine, settings):
        self.engine = engine
        self.settings = settings

    def configured_limit(self) -> int:
        return max(int(self.settings.all()["max_groups_per_account"]), 0)

    def snapshot(self, account_id: int, *, now: datetime | None = None) -> QuotaSnapshot:
        moment = now or utc_now()
        with self.engine.connect() as connection:
            return quota_snapshot_on_connection(
                connection,
                account_id,
                self.configured_limit(),
                now=moment,
            )

    def snapshots(self, account_ids: Iterable[int], *, now: datetime | None = None) -> dict[int, QuotaSnapshot]:
        moment = now or utc_now()
        limit = self.configured_limit()
        ids = list(dict.fromkeys(int(value) for value in account_ids))
        with self.engine.connect() as connection:
            return {
                account_id: quota_snapshot_on_connection(connection, account_id, limit, now=moment)
                for account_id in ids
            }

    def reserve(self, account_id: int, *, now: datetime | None = None) -> QuotaSnapshot | None:
        moment = now or utc_now()
        with self.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                result = reserve_quota_on_connection(
                    connection,
                    account_id,
                    self.configured_limit(),
                    now=moment,
                )
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise

    def reset(self, account_ids: Sequence[int]) -> None:
        ids = list(dict.fromkeys(int(value) for value in account_ids))
        if not ids:
            return
        with self.engine.begin() as connection:
            connection.execute(delete(AccountQuota).where(AccountQuota.account_id.in_(ids)))

    def any_available(self, account_ids: Iterable[int], *, now: datetime | None = None) -> bool:
        return any(snapshot.available > 0 for snapshot in self.snapshots(account_ids, now=now).values())

    def next_unlock(self, account_ids: Iterable[int], *, now: datetime | None = None) -> datetime | None:
        snapshots = self.snapshots(account_ids, now=now).values()
        blocked_ends = [
            snapshot.window_ends_at
            for snapshot in snapshots
            if snapshot.available <= 0 and snapshot.window_ends_at is not None
        ]
        return min(blocked_ends) if blocked_ends else None

    def enrich_account(self, payload: dict, *, now: datetime | None = None) -> dict:
        snapshot = self.snapshot(int(payload["id"]), now=now)
        return {**payload, **snapshot.public()}
