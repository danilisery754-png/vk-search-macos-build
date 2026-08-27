from __future__ import annotations

import sqlite3

from app.db.migrations import upgrade_database


def test_v049_migration_upgrades_v048_dialog_without_losing_existing_data(tmp_path):
    database = tmp_path / "v048-existing.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            CREATE TABLE alembic_version (
                version_num VARCHAR(32) NOT NULL PRIMARY KEY
            );
            INSERT INTO alembic_version(version_num) VALUES ('20260827_0007');

            CREATE TABLE dialogs (
                id INTEGER NOT NULL PRIMARY KEY,
                account_id INTEGER NOT NULL,
                peer_id INTEGER NOT NULL,
                title VARCHAR(500) NOT NULL DEFAULT '',
                avatar_url VARCHAR(1000) NOT NULL DEFAULT '',
                unread_count INTEGER NOT NULL DEFAULT 0,
                can_write BOOLEAN NOT NULL DEFAULT 1,
                write_disabled_reason VARCHAR(120) NOT NULL DEFAULT '',
                last_message_at DATETIME,
                is_pinned BOOLEAN NOT NULL DEFAULT 0,
                pinned_at DATETIME,
                created_at DATETIME,
                updated_at DATETIME
            );
            INSERT INTO dialogs (
                id, account_id, peer_id, title, unread_count, can_write,
                write_disabled_reason, is_pinned
            ) VALUES (41, 7, 202, 'Старый диалог', 3, 1, '', 1);
            """
        )
        connection.commit()
    finally:
        connection.close()

    upgrade_database(database)

    connection = sqlite3.connect(database)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(dialogs)")}
        row = connection.execute(
            """
            SELECT id, account_id, peer_id, title, unread_count, is_pinned,
                   is_archived, archived_at, notifications_muted_by_app,
                   last_message_vk_id, last_message_preview,
                   last_message_outgoing, last_message_deleted
            FROM dialogs WHERE id = 41
            """
        ).fetchone()
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    finally:
        connection.close()

    assert {
        "is_archived",
        "archived_at",
        "notifications_muted_by_app",
        "last_message_vk_id",
        "last_message_preview",
        "last_message_outgoing",
        "last_message_deleted",
    }.issubset(columns)
    assert row == (41, 7, 202, "Старый диалог", 3, 1, 0, None, 0, None, "", 0, 0)
    assert revision == "20260827_0008"
