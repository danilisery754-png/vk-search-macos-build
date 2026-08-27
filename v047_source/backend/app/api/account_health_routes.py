from __future__ import annotations

from fastapi import APIRouter, Request


router = APIRouter(prefix="/api/accounts/health", tags=["accounts"])


@router.post("/check")
async def check_account_health(request: Request, force: bool = False):
    return await request.app.state.services.accounts.check_health(force=force)
