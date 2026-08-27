import sqlite3

from sqlalchemy import create_engine

from app.db.base import Base
from app.db import models  # noqa: F401
from app.services.backup import BackupService


def test_sqlite_backup_is_consistent_and_retention_is_bounded(tmp_path):
    database = tmp_path / "source.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    Base.metadata.create_all(engine)
    service = BackupService(database, tmp_path / "backups", keep=2)

    first = service.create("one")
    second = service.create("two")
    third = service.create("three")

    assert third.exists()
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 2
    with sqlite3.connect(third) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "accounts" in tables and "work_items" in tables


def test_backups_can_be_listed_for_settings_screen(tmp_path):
    database = tmp_path / "source.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    Base.metadata.create_all(engine)
    service = BackupService(database, tmp_path / "backups")

    created = service.create("manual")
    rows = service.list()

    assert rows[0]["name"] == created.name
    assert rows[0]["size"] > 0
    assert rows[0]["created_at"]
