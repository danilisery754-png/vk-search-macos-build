from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import AttemptState
from app.core.time import api_timestamp, utc_from_unix, utc_now
from app.db.models import Account, Dialog, DialogFolder, DialogFolderMember, Message
from app.services.inbox import InboxService as BaseInboxService
from app.vk.client import VkActionResult


class InboxService(BaseInboxService):
    """v0.4.9 inbox behavior layered on the stable v0.4.8 service."""

    @staticmethod
    def _attachment_label(attachments: Any) -> str:
        if not isinstance(attachments, list) or not attachments:
            return ""
        first = attachments[0] if isinstance(attachments[0], dict) else {}
        kind = str(first.get("type") or "")
        if kind == "photo":
            return "Фото"
        if kind == "video":
            return "Видео"
        if kind == "audio_message":
            return "Голосовое сообщение"
        if kind == "doc":
            doc = first.get("doc") if isinstance(first.get("doc"), dict) else {}
            preview = doc.get("preview") if isinstance(doc.get("preview"), dict) else {}
            if "audio_msg" in preview:
                return "Голосовое сообщение"
            return "Документ"
        return "Вложение"

    @classmethod
    def _preview_from_raw(
        cls,
        raw: dict,
        *,
        previous_text: str = "",
        previous_vk_id: int | None = None,
    ) -> tuple[int | None, str, bool, bool]:
        try:
            vk_id = int(raw.get("id")) if raw.get("id") not in (None, "") else None
        except (TypeError, ValueError):
            vk_id = None
        outgoing = bool(raw.get("out"))
        deleted = bool(raw.get("deleted", False))
        text = " ".join(str(raw.get("text") or "").split())
        if deleted:
            if outgoing:
                text = ""
            elif not text and vk_id is not None and vk_id == previous_vk_id:
                text = " ".join(str(previous_text or "").split())
            return vk_id, text, outgoing, True
        if not text:
            text = cls._attachment_label(raw.get("attachments"))
        return vk_id, text, outgoing, False

    @classmethod
    def _preview_from_message(cls, row: Message) -> tuple[int | None, str, bool, bool]:
        text = " ".join(str(row.body or "").split())
        if row.deleted:
            return row.vk_message_id, "" if row.outgoing else text, bool(row.outgoing), True
        if not text:
            try:
                attachments = json.loads(row.attachments_json or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                attachments = []
            text = cls._attachment_label(attachments)
        return row.vk_message_id, text, bool(row.outgoing), False

    @staticmethod
    def _dialog_public(dialog: Dialog, account: Account) -> dict:
        return {
            "id": dialog.id,
            "account_id": dialog.account_id,
            "account_name": account.display_name,
            "peer_id": dialog.peer_id,
            "title": dialog.title,
            "avatar_url": dialog.avatar_url,
            "unread_count": dialog.unread_count,
            "can_write": dialog.can_write,
            "write_disabled_reason": dialog.write_disabled_reason,
            "last_message_at": api_timestamp(dialog.last_message_at),
            "last_message_preview": dialog.last_message_preview or "",
            "last_message_outgoing": bool(dialog.last_message_outgoing),
            "last_message_deleted": bool(dialog.last_message_deleted),
            "is_pinned": bool(dialog.is_pinned),
            "pinned_at": api_timestamp(dialog.pinned_at),
            "is_archived": bool(dialog.is_archived),
            "archived_at": api_timestamp(dialog.archived_at),
        }

    def list_dialogs(
        self,
        *,
        account_id: int | None = None,
        unread: bool | None = None,
        search: str = "",
        folder_id: int | None = None,
        archived: bool = False,
    ) -> list[dict]:
        query = (
            select(Dialog, Account)
            .join(Account, Dialog.account_id == Account.id)
            .where(Dialog.is_archived.is_(bool(archived)))
        )
        if folder_id is not None:
            query = query.join(DialogFolderMember, DialogFolderMember.dialog_id == Dialog.id).where(
                DialogFolderMember.folder_id == folder_id
            )
        if account_id is not None:
            query = query.where(Dialog.account_id == account_id)
        if unread is True:
            query = query.where(Dialog.unread_count > 0)
        elif unread is False:
            query = query.where(Dialog.unread_count == 0)
        if search.strip():
            query = query.where(Dialog.title.ilike(f"%{search.strip()}%"))

        with Session(self.engine) as session:
            if folder_id is not None:
                folder = session.get(DialogFolder, folder_id)
                if folder is None:
                    return []
                if account_id is not None and folder.account_id != account_id:
                    return []
            rows = session.execute(
                query.order_by(
                    Dialog.account_id.asc(),
                    Dialog.is_pinned.desc(),
                    Dialog.pinned_at.desc().nullslast(),
                    Dialog.last_message_at.desc().nullslast(),
                    Dialog.id.desc(),
                )
            ).all()
            dialog_ids = [dialog.id for dialog, _ in rows]
            folder_map: dict[int, list[int]] = {dialog_id: [] for dialog_id in dialog_ids}
            fallback_map: dict[int, Message] = {}
            if dialog_ids:
                memberships = session.execute(
                    select(DialogFolderMember.dialog_id, DialogFolderMember.folder_id).where(
                        DialogFolderMember.dialog_id.in_(dialog_ids)
                    )
                ).all()
                for dialog_id, member_folder_id in memberships:
                    folder_map.setdefault(int(dialog_id), []).append(int(member_folder_id))

                latest = (
                    select(Message.dialog_id, func.max(Message.vk_message_id).label("max_vk_message_id"))
                    .where(Message.dialog_id.in_(dialog_ids))
                    .group_by(Message.dialog_id)
                    .subquery()
                )
                latest_rows = session.scalars(
                    select(Message).join(
                        latest,
                        (Message.dialog_id == latest.c.dialog_id)
                        & (Message.vk_message_id == latest.c.max_vk_message_id),
                    )
                ).all()
                fallback_map = {row.dialog_id: row for row in latest_rows}

            result: list[dict] = []
            for dialog, account in rows:
                public = self._dialog_public(dialog, account)
                if dialog.last_message_vk_id is None and not dialog.last_message_preview:
                    fallback = fallback_map.get(dialog.id)
                    if fallback is not None:
                        vk_id, preview, outgoing, deleted = self._preview_from_message(fallback)
                        public.update(
                            last_message_preview=preview,
                            last_message_outgoing=outgoing,
                            last_message_deleted=deleted,
                        )
                        if public["last_message_at"] is None:
                            public["last_message_at"] = api_timestamp(fallback.sent_at)
                public["folder_ids"] = sorted(folder_map.get(dialog.id, []))
                result.append(public)
            return result

    async def sync_account(self, account_id: int, *, unread_only: bool = False) -> dict:
        response, error = await self._run_vk(
            account_id,
            lambda client: client.get_conversations(unread_only=unread_only),
        )
        if error:
            with Session(self.engine) as session:
                account = session.get(Account, account_id)
                if account:
                    account.last_checked_at = datetime.utcnow()
                    account.last_error = error.reason
                    if error.state is AttemptState.AUTH_REQUIRED:
                        account.auth_status = "requires_login"
                    session.commit()
            return {"ok": False, "error": error.reason, "state": error.state.value}
        if not isinstance(response, dict):
            return {"ok": False, "error": "VK вернул неизвестный формат диалогов"}

        profiles = {int(row["id"]): row for row in response.get("profiles", []) if "id" in row}
        groups = {-abs(int(row["id"])): row for row in response.get("groups", []) if "id" in row}
        changed = 0
        with Session(self.engine) as session:
            for wrapper in response.get("items", []):
                conversation = wrapper.get("conversation", {})
                peer = conversation.get("peer", {})
                peer_id = int(peer.get("id") or 0)
                if not peer_id:
                    continue
                entity = profiles.get(peer_id) or groups.get(peer_id) or {}
                dialog = session.scalar(
                    select(Dialog).where(Dialog.account_id == account_id, Dialog.peer_id == peer_id)
                )
                if dialog is None:
                    dialog = Dialog(account_id=account_id, peer_id=peer_id)
                    session.add(dialog)
                # Archive/pin/folder state is intentionally local and never overwritten by VK sync.
                dialog.title = self._dialog_title(entity, peer_id)
                dialog.avatar_url = str(entity.get("photo_100", ""))
                dialog.unread_count = int(conversation.get("unread_count") or 0)
                can_write = conversation.get("can_write") or {}
                dialog.can_write = bool(can_write.get("allowed", True))
                dialog.write_disabled_reason = str(can_write.get("reason") or "")
                last_message = wrapper.get("last_message") or {}
                if last_message.get("date"):
                    dialog.last_message_at = utc_from_unix(int(last_message["date"]))
                if last_message:
                    vk_id, preview, outgoing, deleted = self._preview_from_raw(
                        last_message,
                        previous_text=dialog.last_message_preview,
                        previous_vk_id=dialog.last_message_vk_id,
                    )
                    if vk_id is not None:
                        dialog.last_message_vk_id = vk_id
                    dialog.last_message_preview = preview
                    dialog.last_message_outgoing = outgoing
                    dialog.last_message_deleted = deleted
                changed += 1
            session.flush()
            account = session.get(Account, account_id)
            if account is not None:
                account.last_checked_at = datetime.utcnow()
                account.last_error = ""
                account.unread_count = self._account_unread_dialogs(session, account_id)
            session.commit()
        return {"ok": True, "dialogs": changed}

    def _store_history_page(self, dialog_id: int, account_id: int, response: dict) -> None:
        in_read = self._read_marker(response.get("in_read"))
        out_read = self._read_marker(response.get("out_read"))
        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            latest_date: datetime | None = dialog.last_message_at if dialog else None
            latest_raw: dict | None = None
            latest_key: tuple[int, int] = (-1, -1)
            for raw in response.get("items", []):
                self._store_raw_message(
                    session,
                    dialog_id,
                    account_id,
                    raw,
                    in_read=in_read,
                    out_read=out_read,
                )
                try:
                    raw_ts = int(raw.get("date") or 0)
                    raw_id = int(raw.get("id") or 0)
                    raw_date = utc_from_unix(raw_ts) if raw_ts else None
                    if raw_date is not None and (latest_date is None or raw_date > latest_date):
                        latest_date = raw_date
                    key = (raw_ts, raw_id)
                    if key > latest_key:
                        latest_key = key
                        latest_raw = raw
                except (TypeError, ValueError, OSError):
                    pass
            if dialog and latest_date:
                dialog.last_message_at = latest_date
            if dialog and latest_raw:
                raw_id = int(latest_raw.get("id") or 0)
                if dialog.last_message_vk_id is None or raw_id >= int(dialog.last_message_vk_id or 0):
                    vk_id, preview, outgoing, deleted = self._preview_from_raw(
                        latest_raw,
                        previous_text=dialog.last_message_preview,
                        previous_vk_id=dialog.last_message_vk_id,
                    )
                    if vk_id is not None:
                        dialog.last_message_vk_id = vk_id
                    dialog.last_message_preview = preview
                    dialog.last_message_outgoing = outgoing
                    dialog.last_message_deleted = deleted
            session.commit()

    @staticmethod
    def _account_unread_dialogs(session: Session, account_id: int) -> int:
        return int(
            session.scalar(
                select(func.count(Dialog.id)).where(
                    Dialog.account_id == account_id,
                    Dialog.unread_count > 0,
                    Dialog.is_archived.is_(False),
                )
            )
            or 0
        )

    async def mark_read(self, dialog_id: int) -> dict:
        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            if dialog is None:
                raise KeyError(dialog_id)
            account_id, peer_id = dialog.account_id, dialog.peer_id
        result = await self._run_vk(account_id, lambda client: client.mark_as_read(peer_id))
        if result.state is not AttemptState.SENT:
            return {"ok": False, "state": result.state.value, "error": result.reason}
        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            if dialog is None:
                raise KeyError(dialog_id)
            dialog.unread_count = 0
            for message in session.scalars(
                select(Message).where(Message.dialog_id == dialog_id, Message.outgoing.is_(False))
            ):
                message.is_read = True
            account = session.get(Account, account_id)
            if account is not None:
                account.unread_count = self._account_unread_dialogs(session, account_id)
            session.commit()
        return {"ok": True, "state": result.state.value, "account_id": account_id}

    async def _set_peer_notifications_best_effort(
        self,
        account_id: int,
        peer_id: int,
        *,
        enabled: bool,
    ) -> bool:
        async def operation(client):
            method = getattr(client, "set_peer_notifications", None)
            if not callable(method):
                return VkActionResult(
                    AttemptState.FAILED_FINAL,
                    error_class="unsupported",
                    reason="VK API этого клиента не поддерживает изменение уведомлений диалога",
                )
            return await method(peer_id, enabled)

        try:
            result = await self._run_vk(account_id, operation)
        except Exception:
            return False
        return isinstance(result, VkActionResult) and result.state is AttemptState.SENT

    async def archive_dialog(self, dialog_id: int) -> dict:
        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            if dialog is None:
                raise KeyError(dialog_id)
            account_id, peer_id = dialog.account_id, dialog.peer_id
            already_archived = bool(dialog.is_archived)
        notifications_changed = False
        if not already_archived:
            notifications_changed = await self._set_peer_notifications_best_effort(
                account_id, peer_id, enabled=False
            )
        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            if dialog is None:
                raise KeyError(dialog_id)
            dialog.is_archived = True
            dialog.archived_at = dialog.archived_at or utc_now()
            if notifications_changed:
                dialog.notifications_muted_by_app = True
            account = session.get(Account, dialog.account_id)
            if account is not None:
                account.unread_count = self._account_unread_dialogs(session, dialog.account_id)
            session.commit()
            return {
                "ok": True,
                "id": dialog.id,
                "is_archived": True,
                "notifications_changed": notifications_changed,
            }

    async def restore_dialog(self, dialog_id: int) -> dict:
        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            if dialog is None:
                raise KeyError(dialog_id)
            account_id, peer_id = dialog.account_id, dialog.peer_id
            should_unmute = bool(dialog.notifications_muted_by_app)
        notifications_changed = False
        if should_unmute:
            notifications_changed = await self._set_peer_notifications_best_effort(
                account_id, peer_id, enabled=True
            )
        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            if dialog is None:
                raise KeyError(dialog_id)
            dialog.is_archived = False
            dialog.archived_at = None
            # Clear this ownership flag only when our matching unmute succeeded.
            if notifications_changed:
                dialog.notifications_muted_by_app = False
            account = session.get(Account, dialog.account_id)
            if account is not None:
                account.unread_count = self._account_unread_dialogs(session, dialog.account_id)
            session.commit()
            return {
                "ok": True,
                "id": dialog.id,
                "is_archived": False,
                "notifications_changed": notifications_changed,
            }
