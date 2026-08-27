from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlalchemy as sa

from app.db.migrations import upgrade_database


V035_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
INSERT INTO alembic_version(version_num) VALUES ('20260825_0001');

CREATE TABLE accounts (
    id INTEGER PRIMARY KEY,
    vk_user_id INTEGER NOT NULL,
    first_name VARCHAR(120) NOT NULL DEFAULT '',
    last_name VARCHAR(120) NOT NULL DEFAULT '',
    profile_url VARCHAR(500) NOT NULL DEFAULT '',
    avatar_url VARCHAR(1000) NOT NULL DEFAULT '',
    note VARCHAR(250) NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT 1,
    auth_status VARCHAR(40) NOT NULL DEFAULT 'requires_login',
    work_status VARCHAR(40) NOT NULL DEFAULT 'stopped',
    last_checked_at DATETIME,
    last_action_at DATETIME,
    last_error TEXT NOT NULL DEFAULT '',
    processed_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    unread_count INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
CREATE TABLE account_secrets (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL UNIQUE,
    encrypted_token BLOB NOT NULL,
    token_fingerprint VARCHAR(64) NOT NULL,
    browser_profile VARCHAR(1000) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
CREATE TABLE settings (
    key VARCHAR(120) PRIMARY KEY,
    value_json TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
CREATE TABLE communities (
    id INTEGER PRIMARY KEY,
    vk_id INTEGER NOT NULL UNIQUE,
    screen_name VARCHAR(250) NOT NULL DEFAULT '',
    name VARCHAR(500) NOT NULL DEFAULT '',
    canonical_url VARCHAR(500) NOT NULL,
    avatar_url VARCHAR(1000) NOT NULL DEFAULT '',
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
CREATE TABLE runs (
    id INTEGER PRIMARY KEY,
    state VARCHAR(40) NOT NULL DEFAULT 'created',
    started_at DATETIME,
    finished_at DATETIME,
    stopped_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
CREATE TABLE work_items (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    community_id INTEGER NOT NULL,
    assigned_account_id INTEGER,
    account_note_snapshot VARCHAR(250) NOT NULL DEFAULT '',
    original_input TEXT NOT NULL DEFAULT '',
    state VARCHAR(40) NOT NULL DEFAULT 'waiting',
    attempts_count INTEGER NOT NULL DEFAULT 0,
    lease_owner VARCHAR(120),
    lease_expires_at DATETIME,
    next_retry_at DATETIME,
    started_at DATETIME,
    completed_at DATETIME,
    last_error TEXT NOT NULL DEFAULT '',
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
CREATE TABLE results (
    id INTEGER PRIMARY KEY,
    work_item_id INTEGER NOT NULL UNIQUE,
    account_id INTEGER,
    message_state VARCHAR(40) NOT NULL DEFAULT 'not_attempted',
    message_reason TEXT NOT NULL DEFAULT '',
    suggested_state VARCHAR(40) NOT NULL DEFAULT 'not_attempted',
    suggested_reason TEXT NOT NULL DEFAULT '',
    outcome VARCHAR(40) NOT NULL DEFAULT 'pending',
    destination VARCHAR(80) NOT NULL DEFAULT '',
    completed_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
CREATE TABLE dialogs (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    peer_id INTEGER NOT NULL,
    title VARCHAR(500) NOT NULL DEFAULT '',
    avatar_url VARCHAR(1000) NOT NULL DEFAULT '',
    unread_count INTEGER NOT NULL DEFAULT 0,
    last_message_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    dialog_id INTEGER NOT NULL,
    vk_message_id INTEGER NOT NULL,
    from_id INTEGER NOT NULL,
    outgoing BOOLEAN NOT NULL DEFAULT 0,
    body TEXT NOT NULL DEFAULT '',
    sent_at DATETIME NOT NULL,
    is_read BOOLEAN NOT NULL DEFAULT 0,
    attachments_json TEXT NOT NULL DEFAULT '[]',
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
"""


def _seed_v035_database(path: Path) -> None:
    now = "2026-08-25 12:00:00"
    with sqlite3.connect(path) as db:
        db.executescript(V035_SCHEMA)
        db.execute(
            "INSERT INTO accounts VALUES (1, 12345, 'Иван', 'Тестов', 'https://vk.com/id12345', '', 'рабочий', 1, 'ok', 'stopped', NULL, NULL, '', 2, 1, 1, 0, ?, ?)",
            (now, now),
        )
        db.execute(
            "INSERT INTO account_secrets VALUES (1, 1, ?, 'fingerprint', 'profiles/1', ?, ?)",
            (b'encrypted-token', now, now),
        )
        db.execute("INSERT INTO settings VALUES ('messages', ?, ?, ?)", ('{\"message_texts\":[\"A\",\"B\"]}', now, now))
        db.execute("INSERT INTO communities VALUES (1, -101, 'one', 'Группа 1', 'https://vk.com/one', '', ?, ?)", (now, now))
        db.execute("INSERT INTO communities VALUES (2, -102, 'two', 'Группа 2', 'https://vk.com/two', '', ?, ?)", (now, now))
        db.execute("INSERT INTO runs VALUES (10, 'completed', ?, ?, NULL, ?, ?)", (now, now, now, now))
        db.execute("INSERT INTO runs VALUES (11, 'running', ?, NULL, NULL, ?, ?)", (now, now, now))
        db.execute("INSERT INTO work_items VALUES (100, 10, 1, 1, 'рабочий', 'one', 'success', 1, NULL, NULL, NULL, ?, ?, '', ?, ?)", (now, now, now, now))
        db.execute("INSERT INTO work_items VALUES (101, 10, 2, 1, 'рабочий', 'two', 'failed', 1, NULL, NULL, NULL, ?, ?, 'closed', ?, ?)", (now, now, now, now))
        db.execute("INSERT INTO work_items VALUES (102, 11, 1, 1, 'рабочий', 'one', 'waiting', 0, NULL, NULL, NULL, NULL, NULL, '', ?, ?)", (now, now))
        db.execute("INSERT INTO results VALUES (200, 100, 1, 'sent', '', 'not_attempted', '', 'success', 'message', ?, ?, ?)", (now, now, now))
        db.execute("INSERT INTO results VALUES (201, 101, 1, 'failed', 'closed', 'failed', 'closed', 'failed', '', ?, ?, ?)", (now, now, now))
        db.execute("INSERT INTO dialogs VALUES (300, 1, -101, 'Группа 1', '', 1, ?, ?, ?)", (now, now, now))
        db.execute("INSERT INTO messages VALUES (400, 1, 300, 5001, -101, 0, 'Здравствуйте', ?, 0, '[]', ?, ?)", (now, now, now))
        db.commit()


def test_v035_database_upgrades_to_v040_without_losing_user_data(tmp_path: Path):
    database = tmp_path / "v035.sqlite3"
    _seed_v035_database(database)

    upgrade_database(database)

    engine = sa.create_engine(f"sqlite+pysqlite:///{database.as_posix()}")
    inspector = sa.inspect(engine)
    assert {column["name"] for column in inspector.get_columns("dialogs")} >= {"can_write", "write_disabled_reason"}
    assert "original_count" in {column["name"] for column in inspector.get_columns("runs")}

    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == "20260825_0003"
        assert conn.execute(sa.text("SELECT vk_user_id, note FROM accounts WHERE id=1")).one() == (12345, "рабочий")
        assert conn.execute(sa.text("SELECT encrypted_token, browser_profile FROM account_secrets WHERE account_id=1")).one() == (b"encrypted-token", "profiles/1")
        assert conn.execute(sa.text("SELECT value_json FROM settings WHERE key='messages'")).scalar_one() == '{"message_texts":["A","B"]}'
        assert conn.execute(sa.text("SELECT COUNT(*) FROM work_items")).scalar_one() == 3
        assert conn.execute(sa.text("SELECT COUNT(*) FROM results")).scalar_one() == 2
        assert conn.execute(sa.text("SELECT body FROM messages WHERE id=400")).scalar_one() == "Здравствуйте"
        assert conn.execute(sa.text("SELECT can_write, write_disabled_reason FROM dialogs WHERE id=300")).one() == (1, "")
        counts = dict(conn.execute(sa.text("SELECT id, original_count FROM runs ORDER BY id")).all())
        assert counts == {10: 2, 11: 1}
