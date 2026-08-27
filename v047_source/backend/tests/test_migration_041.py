from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.db.migrations import upgrade_database


def alembic_config(database_path: Path) -> Config:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path.as_posix()}")
    return config


def test_v040_database_upgrades_to_daily_quota_without_losing_waiting_tail(tmp_path):
    database = tmp_path / "existing-v040.sqlite3"
    config = alembic_config(database)
    command.upgrade(config, "20260825_0003")

    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO accounts (vk_user_id, first_name, last_name, profile_url, avatar_url, note,
                                  enabled, auth_status, work_status,
                                  processed_count, success_count, failed_count, unread_count,
                                  last_checked_at, last_action_at, last_error, created_at, updated_at)
            VALUES (1001, 'Old', 'User', '', '', '', 1, 'ok', 'stopped',
                    0, 0, 0, 0, NULL, NULL, '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """))
        account_id = connection.execute(text("SELECT id FROM accounts WHERE vk_user_id = 1001")).scalar_one()
        connection.execute(text("""
            INSERT INTO communities (vk_id, screen_name, name, canonical_url, avatar_url, created_at, updated_at)
            VALUES (5001, 'club5001', 'Old group', 'https://vk.com/club5001', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """))
        community_id = connection.execute(text("SELECT id FROM communities WHERE vk_id = 5001")).scalar_one()
        connection.execute(text("""
            INSERT INTO runs (state, started_at, stopped_at, finished_at, original_count, created_at, updated_at)
            VALUES ('limit_reached', CURRENT_TIMESTAMP, NULL, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """))
        run_id = connection.execute(text("SELECT max(id) FROM runs")).scalar_one()
        connection.execute(text("""
            INSERT INTO work_items (
                run_id, community_id, assigned_account_id, account_note_snapshot, original_input,
                state, attempts_count, next_retry_at, lease_owner, lease_expires_at,
                started_at, completed_at, last_error, created_at, updated_at
            ) VALUES (
                :run_id, :community_id, :account_id, 'Old User', 'https://vk.com/club5001',
                'assigned', 0, NULL, NULL, NULL, NULL, NULL, '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """), {"run_id": run_id, "community_id": community_id, "account_id": account_id})
    engine.dispose()

    upgrade_database(database)

    upgraded = create_engine(f"sqlite+pysqlite:///{database}")
    inspector = inspect(upgraded)
    assert "account_quotas" in inspector.get_table_names()
    assert "quota_counted_at" in {column["name"] for column in inspector.get_columns("work_items")}
    with upgraded.connect() as connection:
        assert connection.execute(text("SELECT state FROM runs WHERE id = :id"), {"id": run_id}).scalar_one() == "waiting_limit"
        item = connection.execute(text("""
            SELECT state, assigned_account_id, account_note_snapshot
            FROM work_items WHERE run_id = :run_id
        """), {"run_id": run_id}).mappings().one()
        assert item["state"] == "waiting"
        assert item["assigned_account_id"] is None
        assert item["account_note_snapshot"] == ""
    upgraded.dispose()
