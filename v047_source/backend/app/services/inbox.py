from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Callable

from sqlalchemy import Engine, case, func, or_, select
from sqlalchemy.orm import Session

from app.core.enums import AttemptState
from app.core.time import api_timestamp, utc_from_unix, utc_now
from app.db.models import Account, Dialog, DialogFolder, DialogFolderMember, Message
from app.services.accounts import AccountService
from app.vk.client import VkActionResult, VkApiClient


class InboxService:
    def __init__(
        self,
        engine: Engine,
        accounts: AccountService,
        *,
        client_factory: Callable[[str], VkApiClient] = VkApiClient,
    ):
        self.engine = engine
        self.accounts = accounts
        self.client_factory = client_factory

    @staticmethod
    def _json_load(value: str, fallback: Any) -> Any:
        try:
            parsed = json.loads(value or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            return fallback
        return parsed

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
            "is_pinned": bool(dialog.is_pinned),
            "pinned_at": api_timestamp(dialog.pinned_at),
        }

    def list_dialogs(
        self,
        *,
        account_id: int | None = None,
        unread: bool | None = None,
        search: str = "",
        folder_id: int | None = None,
    ) -> list[dict]:
        query = select(Dialog, Account).join(Account, Dialog.account_id == Account.id)
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
                    Dialog.account_id.asc(), Dialog.is_pinned.desc(),
                    Dialog.pinned_at.desc().nullslast(), Dialog.last_message_at.desc().nullslast(), Dialog.id.desc(),
                )
            ).all()
            dialog_ids = [dialog.id for dialog, _ in rows]
            folder_map: dict[int, list[int]] = {dialog_id: [] for dialog_id in dialog_ids}
            if dialog_ids:
                memberships = session.execute(
                    select(DialogFolderMember.dialog_id, DialogFolderMember.folder_id).where(
                        DialogFolderMember.dialog_id.in_(dialog_ids)
                    )
                ).all()
                for dialog_id, member_folder_id in memberships:
                    folder_map.setdefault(int(dialog_id), []).append(int(member_folder_id))
            return [
                {**self._dialog_public(dialog, account), "folder_ids": sorted(folder_map.get(dialog.id, []))}
                for dialog, account in rows
            ]

    def list_folders(self, *, account_id: int | None = None) -> list[dict]:
        with Session(self.engine) as session:
            query = select(DialogFolder)
            if account_id is not None:
                query = query.where(DialogFolder.account_id == account_id)
            rows = list(session.scalars(query.order_by(DialogFolder.account_id.asc(), DialogFolder.name.asc(), DialogFolder.id.asc())).all())
            result: list[dict] = []
            for folder in rows:
                count = session.scalar(
                    select(func.count(DialogFolderMember.id)).where(DialogFolderMember.folder_id == folder.id)
                ) or 0
                result.append({"id": folder.id, "account_id": folder.account_id, "name": folder.name, "dialogs_count": int(count)})
            return result

    def create_folder(self, account_id: int, name: str) -> dict:
        clean = str(name or "").strip()
        if not clean:
            raise ValueError("Название папки не может быть пустым")
        if len(clean) > 120:
            raise ValueError("Название папки слишком длинное")
        with Session(self.engine) as session:
            if session.get(Account, account_id) is None:
                raise KeyError(account_id)
            existing = session.scalar(select(DialogFolder).where(DialogFolder.account_id == account_id, DialogFolder.name == clean))
            if existing is not None:
                raise ValueError("Папка с таким названием уже существует у этого аккаунта")
            folder = DialogFolder(account_id=account_id, name=clean)
            session.add(folder); session.commit(); session.refresh(folder)
            return {"id": folder.id, "account_id": folder.account_id, "name": folder.name, "dialogs_count": 0}

    def update_folder(self, folder_id: int, name: str) -> dict:
        clean = str(name or "").strip()
        if not clean:
            raise ValueError("Название папки не может быть пустым")
        with Session(self.engine) as session:
            folder = session.get(DialogFolder, folder_id)
            if folder is None:
                raise KeyError(folder_id)
            duplicate = session.scalar(select(DialogFolder).where(
                DialogFolder.account_id == folder.account_id, DialogFolder.name == clean, DialogFolder.id != folder.id
            ))
            if duplicate is not None:
                raise ValueError("Папка с таким названием уже существует у этого аккаунта")
            folder.name = clean[:120]; session.commit(); session.refresh(folder)
            count = session.scalar(select(func.count(DialogFolderMember.id)).where(DialogFolderMember.folder_id == folder.id)) or 0
            return {"id": folder.id, "account_id": folder.account_id, "name": folder.name, "dialogs_count": int(count)}

    def delete_folder(self, folder_id: int) -> bool:
        with Session(self.engine) as session:
            folder = session.get(DialogFolder, folder_id)
            if folder is None:
                return False
            session.delete(folder); session.commit(); return True

    def set_dialog_folder(self, folder_id: int, dialog_id: int, enabled: bool) -> dict:
        with Session(self.engine) as session:
            folder = session.get(DialogFolder, folder_id); dialog = session.get(Dialog, dialog_id)
            if folder is None or dialog is None:
                raise KeyError(folder_id if folder is None else dialog_id)
            if folder.account_id != dialog.account_id:
                raise ValueError("Папка и диалог должны принадлежать одному аккаунту")
            member = session.scalar(select(DialogFolderMember).where(
                DialogFolderMember.folder_id == folder_id, DialogFolderMember.dialog_id == dialog_id
            ))
            if enabled and member is None:
                session.add(DialogFolderMember(folder_id=folder_id, dialog_id=dialog_id))
            elif not enabled and member is not None:
                session.delete(member)
            session.commit()
            return {"ok": True, "folder_id": folder_id, "dialog_id": dialog_id, "enabled": bool(enabled)}

    def update_dialog(self, dialog_id: int, *, is_pinned: bool | None = None) -> dict:
        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            if dialog is None:
                raise KeyError(dialog_id)
            account = session.get(Account, dialog.account_id)
            if account is None:
                raise KeyError(dialog.account_id)
            if is_pinned is not None:
                dialog.is_pinned = bool(is_pinned)
                dialog.pinned_at = utc_now() if is_pinned else None
            session.commit()
            session.refresh(dialog)
            return self._dialog_public(dialog, account)

    def list_messages(
        self,
        dialog_id: int,
        *,
        limit: int = 300,
        before_vk_message_id: int | None = None,
    ) -> dict:
        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            if dialog is None:
                raise KeyError(dialog_id)
            account = session.get(Account, dialog.account_id)
            if account is None:
                raise KeyError(dialog.account_id)
            bounded_limit = min(max(limit, 1), 500)
            query = select(Message).where(Message.dialog_id == dialog_id)
            if before_vk_message_id is not None:
                query = query.where(Message.vk_message_id < before_vk_message_id)
            rows = session.scalars(query.order_by(Message.vk_message_id.desc()).limit(bounded_limit)).all()
            chronological = list(reversed(rows))
            local_total = session.scalar(select(func.count(Message.id)).where(Message.dialog_id == dialog_id)) or 0
            oldest_id = chronological[0].vk_message_id if chronological else None
            has_older_local = False
            if oldest_id is not None:
                has_older_local = bool(
                    session.scalar(
                        select(func.count(Message.id)).where(
                            Message.dialog_id == dialog_id,
                            Message.vk_message_id < oldest_id,
                        )
                    )
                )
            return {
                "dialog": self._dialog_public(dialog, account),
                "reply_account": {
                    "id": account.id,
                    "name": account.display_name,
                    "note": account.note,
                    "avatar_url": account.avatar_url,
                },
                "messages": [self._message_public(row) for row in chronological],
                "local_total": int(local_total),
                "has_older_local": has_older_local,
                "next_before_vk_message_id": oldest_id,
            }

    def _message_public(self, row: Message) -> dict:
        reply_message = self._json_load(row.reply_json, {})
        if not isinstance(reply_message, dict) or not reply_message.get("id"):
            reply_message = None
        return {
            "id": row.id,
            "vk_message_id": row.vk_message_id,
            "conversation_message_id": row.conversation_message_id,
            "from_id": row.from_id,
            "outgoing": row.outgoing,
            "body": row.body,
            "sent_at": api_timestamp(row.sent_at),
            "updated_at": api_timestamp(row.updated_at_vk),
            "is_read": row.is_read,
            "deleted": bool(row.deleted),
            "attachments": self._json_load(row.attachments_json, []),
            "reply_message": reply_message,
            "forwarded_messages": self._json_load(row.forwards_json, []),
            "reactions": self._json_load(row.reactions_json, []),
            "raw_meta": self._json_load(row.raw_meta_json, {}),
        }

    async def sync_account(self, account_id: int, *, unread_only: bool = False) -> dict:
        response, error = await self._run_vk(account_id, lambda client: client.get_conversations(unread_only=unread_only))
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
                dialog = session.scalar(select(Dialog).where(Dialog.account_id == account_id, Dialog.peer_id == peer_id))
                if dialog is None:
                    dialog = Dialog(account_id=account_id, peer_id=peer_id)
                    session.add(dialog)
                # Never replace local productivity flags during synchronization.
                dialog.title = self._dialog_title(entity, peer_id)
                dialog.avatar_url = str(entity.get("photo_100", ""))
                dialog.unread_count = int(conversation.get("unread_count") or 0)
                can_write = conversation.get("can_write") or {}
                dialog.can_write = bool(can_write.get("allowed", True))
                dialog.write_disabled_reason = str(can_write.get("reason") or "")
                last_message = wrapper.get("last_message") or {}
                if last_message.get("date"):
                    dialog.last_message_at = utc_from_unix(int(last_message["date"]))
                changed += 1
            session.flush()
            account = session.get(Account, account_id)
            if account is not None:
                account.last_checked_at = datetime.utcnow()
                account.last_error = ""
                account.unread_count = session.scalar(select(func.sum(Dialog.unread_count)).where(Dialog.account_id == account_id)) or 0
            session.commit()
        return {"ok": True, "dialogs": changed}

    async def sync_dialog(self, dialog_id: int, *, offset: int = 0, count: int = 300) -> dict:
        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            if dialog is None:
                raise KeyError(dialog_id)
            account_id, peer_id = dialog.account_id, dialog.peer_id

        remaining = min(max(count, 1), 500)
        current_offset = max(offset, 0)
        fetched = 0
        remote_total: int | None = None
        while remaining:
            chunk = min(remaining, 200)
            response, error = await self._run_vk(
                account_id, lambda client, o=current_offset, c=chunk: client.get_history(peer_id, offset=o, count=c)
            )
            if error:
                return {"ok": False, "error": error.reason, "state": error.state.value}
            if not isinstance(response, dict):
                return {"ok": False, "error": "VK вернул неизвестный формат сообщений"}
            items = response.get("items", [])
            if not isinstance(items, list):
                items = []
            try:
                remote_total = int(response.get("count") or 0)
            except (TypeError, ValueError):
                remote_total = 0
            self._store_history_page(dialog_id, account_id, response)
            page_size = len(items)
            fetched += page_size
            current_offset += page_size
            remaining -= page_size
            if page_size < chunk:
                break

        total = remote_total or current_offset
        return {
            "ok": True,
            "messages": fetched,
            "fetched": fetched,
            "total": total,
            "next_offset": current_offset,
            "has_more": bool(remote_total and current_offset < remote_total),
        }

    def _store_history_page(self, dialog_id: int, account_id: int, response: dict) -> None:
        in_read = self._read_marker(response.get("in_read"))
        out_read = self._read_marker(response.get("out_read"))
        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            latest_date: datetime | None = dialog.last_message_at if dialog else None
            for raw in response.get("items", []):
                self._store_raw_message(session, dialog_id, account_id, raw, in_read=in_read, out_read=out_read)
                try:
                    raw_date = utc_from_unix(int(raw.get("date") or 0))
                    if latest_date is None or raw_date > latest_date:
                        latest_date = raw_date
                except (TypeError, ValueError, OSError):
                    pass
            if dialog and latest_date:
                dialog.last_message_at = latest_date
            session.commit()

    def _store_raw_message(
        self,
        session: Session,
        dialog_id: int,
        account_id: int,
        raw: dict,
        *,
        in_read: int | None = None,
        out_read: int | None = None,
    ) -> Message | None:
        vk_message_id = int(raw.get("id") or 0)
        if not vk_message_id:
            return None
        message = session.scalar(
            select(Message).where(Message.account_id == account_id, Message.vk_message_id == vk_message_id)
        )
        sent_ts = int(raw.get("date") or 0)
        sent_at = utc_from_unix(sent_ts) if sent_ts else utc_now()
        if message is None:
            message = Message(
                account_id=account_id,
                dialog_id=dialog_id,
                vk_message_id=vk_message_id,
                from_id=int(raw.get("from_id") or 0),
                sent_at=sent_at,
            )
            session.add(message)
        message.dialog_id = dialog_id
        message.from_id = int(raw.get("from_id") or message.from_id or 0)
        message.outgoing = bool(raw.get("out"))
        message.body = str(raw.get("text", ""))
        message.sent_at = sent_at
        cmid = raw.get("conversation_message_id")
        message.conversation_message_id = int(cmid) if cmid not in (None, "") else None
        update_time = raw.get("update_time")
        message.updated_at_vk = utc_from_unix(int(update_time)) if update_time else None
        message.deleted = bool(raw.get("deleted", False))
        read_marker = out_read if message.outgoing else in_read
        if read_marker is not None:
            message.is_read = vk_message_id <= read_marker
        message.attachments_json = json.dumps(raw.get("attachments", []), ensure_ascii=False)
        message.reply_json = json.dumps(raw.get("reply_message") or {}, ensure_ascii=False)
        message.forwards_json = json.dumps(raw.get("fwd_messages") or [], ensure_ascii=False)
        message.reactions_json = json.dumps(raw.get("reactions") or [], ensure_ascii=False)
        safe_raw = {
            key: raw.get(key)
            for key in ("random_id", "important", "is_hidden", "keyboard", "template", "payload")
            if key in raw
        }
        message.raw_meta_json = json.dumps(safe_raw, ensure_ascii=False)
        return message

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
            for message in session.scalars(select(Message).where(Message.dialog_id == dialog_id, Message.outgoing.is_(False))):
                message.is_read = True
            account = session.get(Account, account_id)
            if account is not None:
                account.unread_count = session.scalar(select(func.sum(Dialog.unread_count)).where(Dialog.account_id == account_id)) or 0
            session.commit()
        return {"ok": True, "state": result.state.value, "account_id": account_id}

    async def reply(
        self,
        dialog_id: int,
        body: str,
        *,
        reply_to: int | None = None,
        forward: dict[str, Any] | None = None,
        attachment: str | None = None,
        sticker_id: int | None = None,
    ) -> dict:
        text = str(body or "").strip()
        if not any((text, forward, attachment, sticker_id)):
            raise ValueError("Сообщение не может быть пустым")
        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            if dialog is None:
                raise KeyError(dialog_id)
            account_id, peer_id = dialog.account_id, dialog.peer_id
            if reply_to is not None:
                original = session.scalar(
                    select(Message).where(
                        Message.account_id == account_id,
                        Message.vk_message_id == int(reply_to),
                    )
                )
                if original is None:
                    raise ValueError("Исходное сообщение для ответа не найдено в этом аккаунте")
            if forward:
                self._validate_forward(session, account_id, forward)
        async def send_with_optional_fields(client):
            key = f"reply:{dialog_id}:{uuid.uuid4().hex}"
            kwargs: dict[str, Any] = {}
            if reply_to is not None:
                kwargs["reply_to"] = reply_to
            if forward is not None:
                kwargs["forward"] = forward
            if attachment:
                kwargs["attachment"] = attachment
            if sticker_id is not None:
                kwargs["sticker_id"] = sticker_id
            if kwargs:
                return await client.send_message(peer_id, text, key, **kwargs)
            return await client.send_message(peer_id, text, key)

        result = await self._run_vk(account_id, send_with_optional_fields)
        return {
            "ok": result.state is AttemptState.SENT,
            "state": result.state.value,
            "message_id": result.object_id,
            "error": result.reason,
            "account_id": account_id,
        }

    @staticmethod
    def _validate_forward(session: Session, account_id: int, forward: dict[str, Any]) -> None:
        message_ids = forward.get("message_ids") or []
        if message_ids:
            ids = [int(value) for value in message_ids]
            matched = session.scalar(
                select(func.count(Message.id)).where(
                    Message.account_id == account_id,
                    Message.vk_message_id.in_(ids),
                )
            ) or 0
            if matched != len(set(ids)):
                raise ValueError("Пересылать можно только сообщения этого же VK-аккаунта")

    async def edit_message(self, dialog_id: int, vk_message_id: int, body: str, attachment: str | None = None) -> dict:
        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            if dialog is None:
                raise KeyError(dialog_id)
            row = session.scalar(
                select(Message).where(
                    Message.dialog_id == dialog_id,
                    Message.vk_message_id == int(vk_message_id),
                    Message.outgoing.is_(True),
                )
            )
            if row is None:
                raise ValueError("Можно редактировать только своё сообщение из этого диалога")
            account_id, peer_id = dialog.account_id, dialog.peer_id
            cmid = row.conversation_message_id
        result = await self._run_vk(
            account_id,
            lambda client: client.edit_message(
                peer_id,
                message_id=int(vk_message_id),
                conversation_message_id=cmid,
                message=body,
                attachment=attachment,
            ),
        )
        return {"ok": result.state is AttemptState.SENT, "state": result.state.value, "error": result.reason}

    async def delete_message(self, dialog_id: int, vk_message_id: int, *, delete_for_all: bool = True) -> dict:
        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            if dialog is None:
                raise KeyError(dialog_id)
            row = session.scalar(select(Message).where(Message.dialog_id == dialog_id, Message.vk_message_id == int(vk_message_id)))
            if row is None:
                raise ValueError("Сообщение не найдено")
            account_id = dialog.account_id
        result = await self._run_vk(account_id, lambda client: client.delete_message(vk_message_id, delete_for_all=delete_for_all))
        if result.state is AttemptState.SENT:
            with Session(self.engine) as session:
                row = session.scalar(select(Message).where(Message.dialog_id == dialog_id, Message.vk_message_id == int(vk_message_id)))
                if row:
                    row.deleted = True
                    session.commit()
        return {"ok": result.state is AttemptState.SENT, "state": result.state.value, "error": result.reason}

    async def set_reaction(self, dialog_id: int, vk_message_id: int, reaction_id: int | None) -> dict:
        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            if dialog is None:
                raise KeyError(dialog_id)
            row = session.scalar(select(Message).where(Message.dialog_id == dialog_id, Message.vk_message_id == int(vk_message_id)))
            if row is None or row.conversation_message_id is None:
                raise ValueError("VK не вернул ID сообщения для реакции")
            account_id, peer_id, cmid = dialog.account_id, dialog.peer_id, row.conversation_message_id
        if reaction_id is None:
            result = await self._run_vk(account_id, lambda client: client.delete_reaction(peer_id, cmid))
        else:
            result = await self._run_vk(account_id, lambda client: client.set_reaction(peer_id, cmid, reaction_id))
        return {"ok": result.state is AttemptState.SENT, "state": result.state.value, "error": result.reason}

    async def set_activity(self, dialog_id: int, activity: str = "typing") -> dict:
        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            if dialog is None:
                raise KeyError(dialog_id)
            account_id, peer_id = dialog.account_id, dialog.peer_id
        result = await self._run_vk(account_id, lambda client: client.set_activity(peer_id, activity))
        return {"ok": result.state is AttemptState.SENT, "state": result.state.value, "error": result.reason}

    def search_local(self, dialog_id: int, query: str, *, limit: int = 100) -> list[dict]:
        value = query.strip()
        if not value:
            return []
        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            if dialog is None:
                raise KeyError(dialog_id)
            rows = session.scalars(
                select(Message)
                .where(Message.dialog_id == dialog_id, Message.body.ilike(f"%{value}%"))
                .order_by(Message.vk_message_id.desc())
                .limit(min(max(limit, 1), 200))
            ).all()
            return [self._message_public(row) for row in rows]

    async def media_history(self, dialog_id: int, media_type: str, *, start_from: str | None = None, count: int = 100) -> dict:
        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            if dialog is None:
                raise KeyError(dialog_id)
            account_id, peer_id = dialog.account_id, dialog.peer_id
        response, error = await self._run_vk(
            account_id,
            lambda client: client.get_history_attachments(peer_id, media_type=media_type, start_from=start_from, count=count),
        )
        if error:
            return {"ok": False, "state": error.state.value, "error": error.reason, "items": []}
        return {"ok": True, "items": (response or {}).get("items", []) if isinstance(response, dict) else [], "next_from": (response or {}).get("next_from") if isinstance(response, dict) else None}

    async def _run_vk(self, account_id: int, operation):
        runner = getattr(self.accounts, "run_vk", None)
        if callable(runner):
            return await runner(account_id, operation, client_factory=self.client_factory)
        token = self.accounts.get_token(account_id)
        client = self.client_factory(token)
        try:
            return await operation(client)
        finally:
            token = ""
            await client.aclose()

    @staticmethod
    def _dialog_title(entity: dict, peer_id: int) -> str:
        if "name" in entity:
            return str(entity.get("name") or f"Сообщество {abs(peer_id)}")
        full_name = f"{entity.get('first_name', '')} {entity.get('last_name', '')}".strip()
        return full_name or f"Диалог {peer_id}"

    @staticmethod
    def _read_marker(value) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
