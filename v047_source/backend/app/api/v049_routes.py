from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request


router = APIRouter(prefix="/api")


def services(request: Request):
    return request.app.state.services


@router.get("/inbox/archive")
def archived_dialogs(
    request: Request,
    account_id: int | None = None,
    search: str = "",
):
    return services(request).inbox.list_dialogs(
        account_id=account_id,
        search=search,
        archived=True,
    )


@router.post("/inbox/dialogs/{dialog_id}/archive")
async def archive_dialog(dialog_id: int, request: Request):
    try:
        return await services(request).inbox.archive_dialog(dialog_id)
    except KeyError as exc:
        raise HTTPException(404, "Диалог не найден") from exc


@router.post("/inbox/dialogs/{dialog_id}/restore")
async def restore_dialog(dialog_id: int, request: Request):
    try:
        return await services(request).inbox.restore_dialog(dialog_id)
    except KeyError as exc:
        raise HTTPException(404, "Диалог не найден") from exc
