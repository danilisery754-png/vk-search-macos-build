from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config


def upgrade_database(database_path: Path, backend_root: Path | None = None) -> None:
    root = backend_root or Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path.as_posix()}")
    command.upgrade(config, "head")

