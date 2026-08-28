from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.account_health_routes import router as account_health_router
from app.api.routes import router
from app.api.v049_routes import router as v049_router
from app.core.config import AppConfig
from app.db.migrations import upgrade_database
from app.db.session import create_sqlite_engine
from app.services.accounts_v049 import AccountService
from app.services.backup import BackupService
from app.services.dashboard import DashboardService
from app.services.inbox_v049_runtime import InboxService
from app.services.logs import EventLogService
from app.services.processor import WorkProcessor
from app.services.queue import QueueRepository
from app.services.quick_replies import QuickReplyService
from app.services.results import ResultsService
from app.services.runs import RunService
from app.services.settings import SettingsService
from app.services.worklist import WorkListService
from app.workers.supervisor import WorkerSupervisor
from app.workers.inbox_sync import InboxSyncWorker


@dataclass(slots=True)
class Services:
    config: AppConfig
    engine: object
    queue: QueueRepository
    accounts: AccountService
    backup: BackupService
    settings: SettingsService
    worklist: WorkListService
    runs: RunService
    results: ResultsService
    dashboard: DashboardService
    logs: EventLogService
    inbox: InboxService
    quick_replies: QuickReplyService
    processor: WorkProcessor
    supervisor: WorkerSupervisor
    inbox_sync: InboxSyncWorker


def build_services(config: AppConfig) -> Services:
    config.ensure_directories()
    upgrade_database(config.database_path)
    engine = create_sqlite_engine(config.database_path)
    queue = QueueRepository(engine)
    settings = SettingsService(engine)
    accounts = AccountService(
        engine,
        config.profiles_dir,
        config.data_dir / "development-secret.key",
    )
    backup = BackupService(config.database_path, config.data_dir / "backups")
    worklist = WorkListService(engine, accounts)
    runs = RunService(engine, settings)
    results = ResultsService(engine)
    dashboard = DashboardService(engine)
    logs = EventLogService(engine)
    inbox = InboxService(engine, accounts)
    quick_replies = QuickReplyService(engine)
    processor = WorkProcessor(engine, queue, accounts, settings, logs=logs)
    supervisor = WorkerSupervisor(engine, processor, settings, runs, logs)
    inbox_sync = InboxSyncWorker(engine, inbox, settings, logs)
    return Services(
        config, engine, queue, accounts, backup, settings, worklist, runs,
        results, dashboard, logs, inbox, quick_replies, processor, supervisor, inbox_sync,
    )


def create_app(config: AppConfig | None = None) -> FastAPI:
    resolved_config = config or AppConfig()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = build_services(resolved_config)
        suspended = app.state.services.runs.suspend_unconfirmed_on_startup()
        recovered = app.state.services.queue.recover_expired()
        try:
            app.state.services.backup.create("startup")
        except Exception as exc:
            app.state.services.logs.add(f"Не удалось создать резервную копию: {exc}", level="warning")
        if suspended:
            app.state.services.logs.add(
                f"После перезапуска приостановлено запусков: {suspended}. Для продолжения нажмите «Запустить» или «Продолжить».",
                level="warning",
            )
        if recovered:
            app.state.services.logs.add(
                f"После перезапуска найдено незавершённых действий: {recovered}. Повторная отправка заблокирована до сверки.",
                level="warning",
            )
        app.state.services.supervisor.start()
        app.state.services.inbox_sync.start()
        yield
        await app.state.services.inbox_sync.stop()
        await app.state.services.supervisor.stop()
        app.state.services.engine.dispose()

    app = FastAPI(title="VK Search", version="0.4.10", lifespan=lifespan)
    app.include_router(router)
    app.include_router(account_health_router)
    app.include_router(v049_router)

    frontend = resolved_config.resolved_frontend_dir
    assets = frontend / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/vk-search-icon.jpg", include_in_schema=False)
    async def frontend_icon():
        icon = frontend / "vk-search-icon.jpg"
        if not icon.exists():
            raise HTTPException(404, "Иконка VK Search не найдена")
        return FileResponse(icon, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend_fallback(path: str):
        index = frontend / "index.html"
        if index.exists():
            return FileResponse(index, headers={"Cache-Control": "no-store"})
        return FileResponse(frontend / "missing.html") if (frontend / "missing.html").exists() else {
            "message": "Интерфейс ещё не собран",
            "api": "/docs",
        }

    return app


app = create_app()
