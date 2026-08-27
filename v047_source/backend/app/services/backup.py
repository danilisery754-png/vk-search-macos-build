from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class BackupService:
    def __init__(self, database_path: Path, backup_dir: Path, *, keep: int = 14):
        self.database_path = Path(database_path)
        self.backup_dir = Path(backup_dir)
        self.keep = max(1, keep)

    def create(self, label: str = "auto") -> Path:
        if not self.database_path.exists():
            raise FileNotFoundError(self.database_path)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        safe_label = re.sub(r"[^A-Za-z0-9_-]+", "-", label).strip("-") or "backup"
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        destination = self.backup_dir / f"{stamp}-{safe_label}.sqlite3"
        with sqlite3.connect(self.database_path) as source, sqlite3.connect(destination) as target:
            source.backup(target)
        self._apply_retention()
        return destination

    def list(self) -> list[dict]:
        if not self.backup_dir.exists():
            return []
        rows = sorted(
            self.backup_dir.glob("*.sqlite3"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return [
            {
                "name": path.name,
                "size": path.stat().st_size,
                "created_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
            }
            for path in rows
        ]

    def _apply_retention(self) -> None:
        backups = sorted(self.backup_dir.glob("*.sqlite3"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in backups[self.keep :]:
            path.unlink(missing_ok=True)
