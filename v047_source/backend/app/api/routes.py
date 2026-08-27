from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from app.api.schemas import (
    AccountUpdateRequest,
    ExportRequest,
    ImportGroupsRequest,
    DialogUpdateRequest,
    DialogFolderCreateRequest,
    DialogFolderUpdateRequest,
    InboxReplyRequest,
    MessageActivityRequest,
    MessageDeleteRequest,
    MessageEditRequest,
    MessageReactionRequest,
    QuickReplyRequest,
    RemoveItemsRequest,
    SettingsUpdateRequest,
    WorkStartRequest,
)
from app.core.enums import FinalOutcome


router = APIRouter(prefix="/api")


def services(request: Request):
    return request.app.state.services


@router.get("/health")
def health(request: Request):
    return {"ok": True, "version": "0.4.9", "work": services(request).runs.current_state()}


@router.get("/dashboard")
def dashboard(request: Request):
    return services(request).dashboard.snapshot()


@router.get("/accounts")
def accounts(request: Request):
    svc = services(request)
    rows = svc.accounts.list_accounts()
    quota = getattr(svc.runs, "quota", None)
    if quota is None:
        return rows
    return [quota.enrich_account(row) for row in rows]


@router.post("/accounts/authorize", status_code=202)
async def authorize_account(request: Request, account_id: int | None = None):
    try:
        return services(request).accounts.start_authorization(account_id).public()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/accounts/authorize/{job_id}")
def authorization_status(job_id: str, request: Request):
    try:
        return services(request).accounts.auth_status(job_id)
    except KeyError as exc:
        raise HTTPException(404, "Авторизация не найдена") from exc


@router.post("/accounts/authorize/{job_id}/confirm")
def confirm_authorization(job_id: str, request: Request):
    try:
        return services(request).accounts.confirm_authorization(job_id)
    except KeyError as exc:
        raise HTTPException(404, "Авторизация не найдена") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/accounts/{account_id}/open-messages", status_code=202)
async def open_account_messages(account_id: int, request: Request):
    try:
        return services(request).accounts.start_open_messages(account_id).public()
    except KeyError as exc:
        raise HTTPException(404, "Аккаунт не найден") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/accounts/open-messages/{job_id}")
def open_messages_status(job_id: str, request: Request):
    try:
        return services(request).accounts.browser_status(job_id)
    except KeyError as exc:
        raise HTTPException(404, "Открытие сообщений не найдено") from exc


@router.patch("/accounts/{account_id}")
def update_account(account_id: int, payload: AccountUpdateRequest, request: Request):
    try:
        result = services(request).accounts.update_account(
            account_id, note=payload.note, enabled=payload.enabled
        )
        if payload.enabled is False:
            services(request).queue.release_unstarted(account_id)
        quota = getattr(services(request).runs, "quota", None)
        return quota.enrich_account(result) if quota is not None else result
    except KeyError as exc:
        raise HTTPException(404, "Аккаунт не найден") from exc


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int, request: Request):
    services(request).queue.release_unstarted(account_id)
    try:
        if not services(request).accounts.delete_account(account_id):
            raise HTTPException(404, "Аккаунт не найден")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True}


@router.post("/groups/import")
async def import_groups(payload: ImportGroupsRequest, request: Request):
    if payload.mode == "cancel":
        return {
            "found": 0,
            "added": 0,
            "duplicates": 0,
            "unresolved": [],
            "replaced": 0,
            "cancelled": True,
        }
    try:
        result = (await services(request).worklist.import_text(payload.text, mode=payload.mode)).public()
        return {**result, "cancelled": False}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/groups")
def list_groups(
    request: Request,
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    return services(request).worklist.list_active(limit=limit, offset=offset)


@router.post("/groups/remove")
def remove_groups(payload: RemoveItemsRequest, request: Request):
    svc = services(request)
    removed = svc.worklist.remove_unstarted(payload.ids)
    state = svc.runs.current_state()
    if removed and state.get("run_id") is not None:
        try:
            svc.runs.reconcile_state(int(state["run_id"]))
        except KeyError:
            pass
    return {"removed": removed}


@router.get("/groups/{item_id}/history")
def group_history(item_id: int, request: Request):
    try:
        return services(request).worklist.history(item_id)
    except KeyError as exc:
        raise HTTPException(404, "История группы не найдена") from exc


@router.post("/work/start")
def start_work(request: Request, payload: WorkStartRequest | None = None):
    try:
        ignore_limits = bool(
            payload and payload.mode == "reset_limits_for_participating_accounts"
        )
        result = services(request).runs.start(ignore_limits=ignore_limits)
        services(request).supervisor.start()
        if ignore_limits:
            services(request).logs.add("Работа запущена с ручным сбросом суточных лимитов")
        else:
            services(request).logs.add("Работа запущена с учётом суточных лимитов")
        return result
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/work/pause")
def pause_work(request: Request):
    result = services(request).runs.pause()
    services(request).logs.add("Работа поставлена на паузу")
    return result


@router.post("/work/resume")
def resume_work(request: Request):
    result = services(request).runs.resume()
    services(request).supervisor.start()
    services(request).logs.add("Работа продолжена")
    return result


@router.post("/work/stop")
def stop_work(request: Request):
    result = services(request).runs.stop()
    services(request).logs.add("Работа остановлена")
    return result


@router.get("/runs")
def runs_history(request: Request):
    return services(request).runs.list_history()


@router.delete("/runs/{run_id}")
def delete_run(run_id: int, request: Request):
    try:
        if not services(request).runs.delete_history(run_id):
            raise HTTPException(404, "Запуск не найден")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True}


@router.get("/results/success")
def successful_results(request: Request, search: str = "", limit: int = 200, offset: int = 0, run_id: int | None = None):
    return services(request).results.list(FinalOutcome.SUCCESS, run_id=run_id, search=search, limit=limit, offset=offset)


@router.get("/results/failed")
def failed_results(request: Request, search: str = "", limit: int = 200, offset: int = 0, run_id: int | None = None):
    return services(request).results.list(FinalOutcome.FAILED, run_id=run_id, search=search, limit=limit, offset=offset)


@router.post("/results/{kind}/export")
def export_results(kind: str, payload: ExportRequest, request: Request):
    if kind not in {"success", "failed"}:
        raise HTTPException(404, "Раздел результатов не найден")
    outcome = FinalOutcome.SUCCESS if kind == "success" else FinalOutcome.FAILED
    try:
        content, media_type = services(request).results.export(outcome, payload.mode, payload.selected_ids, run_id=payload.run_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    extension = "txt" if payload.mode == "links" else payload.mode
    russian_name = "успешно-написали" if kind == "success" else "не-удалось-написать"
    disposition = f"attachment; filename*=UTF-8''{quote(f'{russian_name}.{extension}')}"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": disposition})


@router.get("/settings")
def get_settings(request: Request):
    return services(request).settings.all()


@router.patch("/settings")
def update_settings(payload: SettingsUpdateRequest, request: Request):
    try:
        return services(request).settings.update(payload.values)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/quick-replies")
def list_quick_replies(request: Request):
    return services(request).quick_replies.list()


@router.post("/quick-replies", status_code=201)
def create_quick_reply(payload: QuickReplyRequest, request: Request):
    try:
        return services(request).quick_replies.create(payload.text)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.patch("/quick-replies/{reply_id}")
def update_quick_reply(reply_id: str, payload: QuickReplyRequest, request: Request):
    try:
        return services(request).quick_replies.update(reply_id, payload.text)
    except KeyError as exc:
        raise HTTPException(404, "Шаблон не найден") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/quick-replies/{reply_id}")
def delete_quick_reply(reply_id: str, request: Request):
    if not services(request).quick_replies.delete(reply_id):
        raise HTTPException(404, "Шаблон не найден")
    return {"ok": True}


@router.get("/backups")
def list_backups(request: Request):
    return services(request).backup.list()


@router.post("/backups", status_code=201)
def create_backup(request: Request):
    path = services(request).backup.create("manual")
    services(request).logs.add("Резервная копия создана вручную")
    return {"ok": True, "name": path.name}


@router.get("/logs")
def get_logs(
    request: Request,
    limit: int = Query(300, ge=1, le=2000),
    account_id: int | None = None,
    work_item_id: int | None = None,
    category: str | None = None,
    level: str | None = None,
):
    return services(request).logs.list(
        limit=limit, account_id=account_id, work_item_id=work_item_id, category=category, level=level
    )


@router.get("/inbox/dialogs")
def dialogs(
    request: Request,
    account_id: int | None = None,
    unread: bool | None = None,
    search: str = "",
    folder_id: int | None = None,
):
    return services(request).inbox.list_dialogs(account_id=account_id, unread=unread, search=search, folder_id=folder_id)


@router.get("/inbox/folders")
def dialog_folders(request: Request, account_id: int | None = None):
    return services(request).inbox.list_folders(account_id=account_id)


@router.post("/inbox/folders", status_code=201)
def create_dialog_folder(payload: DialogFolderCreateRequest, request: Request):
    try:
        return services(request).inbox.create_folder(payload.account_id, payload.name)
    except KeyError as exc:
        raise HTTPException(404, "Аккаунт не найден") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.patch("/inbox/folders/{folder_id}")
def update_dialog_folder(folder_id: int, payload: DialogFolderUpdateRequest, request: Request):
    try:
        return services(request).inbox.update_folder(folder_id, payload.name)
    except KeyError as exc:
        raise HTTPException(404, "Папка не найдена") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/inbox/folders/{folder_id}")
def delete_dialog_folder(folder_id: int, request: Request):
    if not services(request).inbox.delete_folder(folder_id):
        raise HTTPException(404, "Папка не найдена")
    return {"ok": True}


@router.put("/inbox/folders/{folder_id}/dialogs/{dialog_id}")
def add_dialog_to_folder(folder_id: int, dialog_id: int, request: Request):
    try:
        return services(request).inbox.set_dialog_folder(folder_id, dialog_id, True)
    except KeyError as exc:
        raise HTTPException(404, "Папка или диалог не найден") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/inbox/folders/{folder_id}/dialogs/{dialog_id}")
def remove_dialog_from_folder(folder_id: int, dialog_id: int, request: Request):
    try:
        return services(request).inbox.set_dialog_folder(folder_id, dialog_id, False)
    except KeyError as exc:
        raise HTTPException(404, "Папка или диалог не найден") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/inbox/sync")
async def sync_inbox(request: Request, account_id: int):
    return await services(request).inbox.sync_account(account_id)


@router.get("/inbox/dialogs/{dialog_id}")
def dialog_messages(
    dialog_id: int,
    request: Request,
    limit: int = Query(300, ge=1, le=500),
    before_vk_message_id: int | None = Query(None, ge=1),
):
    try:
        return services(request).inbox.list_messages(
            dialog_id, limit=limit, before_vk_message_id=before_vk_message_id
        )
    except KeyError as exc:
        raise HTTPException(404, "Диалог не найден") from exc


@router.post("/inbox/dialogs/{dialog_id}/sync")
async def sync_dialog(
    dialog_id: int,
    request: Request,
    offset: int = Query(0, ge=0),
    count: int = Query(300, ge=1, le=500),
):
    try:
        return await services(request).inbox.sync_dialog(dialog_id, offset=offset, count=count)
    except KeyError as exc:
        raise HTTPException(404, "Диалог не найден") from exc


@router.post("/inbox/dialogs/{dialog_id}/read")
async def mark_dialog_read(dialog_id: int, request: Request):
    try:
        return await services(request).inbox.mark_read(dialog_id)
    except KeyError as exc:
        raise HTTPException(404, "Диалог не найден") from exc


@router.patch("/inbox/dialogs/{dialog_id}")
def update_dialog(dialog_id: int, payload: DialogUpdateRequest, request: Request):
    try:
        return services(request).inbox.update_dialog(dialog_id, is_pinned=payload.is_pinned)
    except KeyError as exc:
        raise HTTPException(404, "Диалог не найден") from exc


@router.post("/inbox/dialogs/{dialog_id}/reply")
async def reply(dialog_id: int, payload: InboxReplyRequest, request: Request):
    try:
        return await services(request).inbox.reply(
            dialog_id,
            payload.body,
            reply_to=payload.reply_to,
            forward=payload.forward,
            attachment=payload.attachment,
            sticker_id=payload.sticker_id,
        )
    except KeyError as exc:
        raise HTTPException(404, "Диалог не найден") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.patch("/inbox/dialogs/{dialog_id}/messages/{vk_message_id}")
async def edit_message(dialog_id: int, vk_message_id: int, payload: MessageEditRequest, request: Request):
    try:
        return await services(request).inbox.edit_message(dialog_id, vk_message_id, payload.body, payload.attachment)
    except KeyError as exc:
        raise HTTPException(404, "Диалог не найден") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/inbox/dialogs/{dialog_id}/messages/{vk_message_id}")
async def delete_message(dialog_id: int, vk_message_id: int, request: Request, delete_for_all: bool = True):
    try:
        return await services(request).inbox.delete_message(dialog_id, vk_message_id, delete_for_all=delete_for_all)
    except KeyError as exc:
        raise HTTPException(404, "Диалог не найден") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/inbox/dialogs/{dialog_id}/messages/{vk_message_id}/reaction")
async def message_reaction(dialog_id: int, vk_message_id: int, payload: MessageReactionRequest, request: Request):
    try:
        return await services(request).inbox.set_reaction(dialog_id, vk_message_id, payload.reaction_id)
    except KeyError as exc:
        raise HTTPException(404, "Диалог не найден") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/inbox/dialogs/{dialog_id}/activity")
async def message_activity(dialog_id: int, payload: MessageActivityRequest, request: Request):
    try:
        return await services(request).inbox.set_activity(dialog_id, payload.activity)
    except KeyError as exc:
        raise HTTPException(404, "Диалог не найден") from exc


@router.get("/inbox/dialogs/{dialog_id}/search")
def search_dialog(dialog_id: int, request: Request, q: str, limit: int = Query(100, ge=1, le=200)):
    try:
        return services(request).inbox.search_local(dialog_id, q, limit=limit)
    except KeyError as exc:
        raise HTTPException(404, "Диалог не найден") from exc


@router.get("/inbox/dialogs/{dialog_id}/media")
async def dialog_media(
    dialog_id: int,
    request: Request,
    media_type: str = "photo",
    start_from: str | None = None,
    count: int = Query(100, ge=1, le=200),
):
    try:
        return await services(request).inbox.media_history(
            dialog_id, media_type, start_from=start_from, count=count
        )
    except KeyError as exc:
        raise HTTPException(404, "Диалог не найден") from exc


@router.get("/diagnostics")
def diagnostics(request: Request):
    svc = services(request)
    return {
        "database": "ok",
        "data_dir": str(svc.config.data_dir),
        "frontend": svc.config.resolved_frontend_dir.exists(),
        "accounts": svc.accounts.list_accounts(),
        "work": svc.runs.current_state(),
    }
