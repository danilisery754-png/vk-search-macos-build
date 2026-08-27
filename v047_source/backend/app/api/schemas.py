from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ImportGroupsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5_000_000)
    mode: Literal["append", "replace_waiting", "cancel"] = "append"


class WorkStartRequest(BaseModel):
    mode: Literal["respect_limits", "reset_limits_for_participating_accounts"] = "respect_limits"


class AccountUpdateRequest(BaseModel):
    note: str | None = Field(default=None, max_length=250)
    enabled: bool | None = None


class SettingsUpdateRequest(BaseModel):
    values: dict[str, Any]


class RemoveItemsRequest(BaseModel):
    ids: list[int]


class ExportRequest(BaseModel):
    mode: Literal["links", "tsv", "csv", "xlsx"] = "csv"
    selected_ids: list[int] | None = None
    run_id: int | None = None


class InboxReplyRequest(BaseModel):
    body: str = Field(default="", max_length=4096)
    reply_to: int | None = Field(default=None, ge=1)
    forward: dict[str, Any] | None = None
    attachment: str | None = Field(default=None, max_length=5000)
    sticker_id: int | None = Field(default=None, ge=1)


class QuickReplyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class DialogUpdateRequest(BaseModel):
    is_pinned: bool | None = None


class DialogFolderCreateRequest(BaseModel):
    account_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=120)


class DialogFolderUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class MessageEditRequest(BaseModel):
    body: str = Field(default="", max_length=4096)
    attachment: str | None = Field(default=None, max_length=5000)


class MessageDeleteRequest(BaseModel):
    delete_for_all: bool = True


class MessageReactionRequest(BaseModel):
    reaction_id: int | None = Field(default=None, ge=1)


class MessageActivityRequest(BaseModel):
    activity: Literal["typing", "audiomessage"] = "typing"
