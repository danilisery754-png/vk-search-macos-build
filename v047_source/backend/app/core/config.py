from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


APP_NAME = "VK Search"
LEGACY_APP_NAME = "VK Outreach Manager"


def default_data_dir() -> Path:
    override = os.environ.get("VK_OUTREACH_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        new_path = Path.home() / "Library" / "Application Support" / APP_NAME
        legacy_path = Path.home() / "Library" / "Application Support" / LEGACY_APP_NAME
        return legacy_path if legacy_path.exists() and not new_path.exists() else new_path
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "vk-outreach-manager"


def resource_dir() -> Path:
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return Path(frozen)
    return Path(__file__).resolve().parents[3]


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VK_OUTREACH_", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 18741
    data_dir: Path = default_data_dir()
    log_level: str = "INFO"
    frontend_dir: Path | None = None

    @property
    def database_path(self) -> Path:
        return self.data_dir / "data" / "vk_outreach.sqlite3"

    @property
    def profiles_dir(self) -> Path:
        return self.data_dir / "browser_profiles"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def resolved_frontend_dir(self) -> Path:
        return self.frontend_dir or (resource_dir() / "frontend" / "dist")

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.database_path.parent, self.profiles_dir, self.logs_dir, self.exports_dir):
            path.mkdir(parents=True, exist_ok=True)

