from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import AttemptState
from app.db.models import Dialog, DialogFolder, DialogFolderMember, Message
from app.services.inbox_v049 import InboxService as V049InboxService
from app.vk.client import VkActionResult


class InboxService(V049InboxService):
    """Final v0.4.9 inbox runtime safeguards."""

    def list_dialogs(
        self,
        *,
        account_id: int | None = None,
        unread: bool | None = None,
        search: str = "",
        folder_id: int | None = None,
        archived: bool = False,
    ) -> list[dict]:
        rows = super().list_dialogs(
            account_id=account_id,
            unread=unread,
            search=search,
            folder_id=folder_id,
            archived=archived,
        )
        missing_ids = [
            int(row["id"])
            for row in rows
            if row.get("last_message_deleted") is True
            and row.get("last_message_outgoing") is False
            and not str(row.get("last_message_preview") or "").strip()
        ]
        if not missing_ids:
            return rows

        # Upgrade fallback: v0.4.8 may already know the old incoming text in
        # Message even though the newly-added Dialog preview columns are empty.
        # Resolve all such dialogs in one local SQL query; no extra VK calls.
        with Session(self.engine) as session:
            local_rows = session.scalars(
                select(Message)
                .join(Dialog, Dialog.id == Message.dialog_id)
                .where(
                    Dialog.id.in_(missing_ids),
                    Dialog.last_message_vk_id.is_not(None),
                    Message.vk_message_id == Dialog.last_message_vk_id,
                )
            ).all()
            known = {
                int(message.dialog_id): " ".join(str(message.body or "").split())
                for message in local_rows
                if str(message.body or "").strip()
            }
        for row in rows:
            text = known.get(int(row["id"]))
            if text:
                row["last_message_preview"] = text
        return rows

    def list_folders(self, *, account_id: int | None = None) -> list[dict]:
        """Keep archived membership, but count only dialogs visible outside Archive."""
        with Session(self.engine) as session:
            query = select(DialogFolder)
            if account_id is not None:
                query = query.where(DialogFolder.account_id == account_id)
            folders = list(
                session.scalars(
                    query.order_by(
                        DialogFolder.account_id.asc(),
                        DialogFolder.name.asc(),
                        DialogFolder.id.asc(),
                    )
                ).all()
            )
            folder_ids = [folder.id for folder in folders]
            visible_counts: dict[int, int] = {}
            if folder_ids:
                visible_counts = {
                    int(folder_id): int(count)
                    for folder_id, count in session.execute(
                        select(DialogFolderMember.folder_id, func.count(DialogFolderMember.id))
                        .join(Dialog, Dialog.id == DialogFolderMember.dialog_id)
                        .where(
                            DialogFolderMember.folder_id.in_(folder_ids),
                            Dialog.is_archived.is_(False),
                        )
                        .group_by(DialogFolderMember.folder_id)
                    ).all()
                }
            return [
                {
                    "id": folder.id,
                    "account_id": folder.account_id,
                    "name": folder.name,
                    "dialogs_count": visible_counts.get(folder.id, 0),
                }
                for folder in folders
            ]

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
        """Preserve known incoming text when VK later reports the message deleted.

        The extra lookup is deliberately limited to the one edge case that
        needs previous local text; normal history sync keeps the v0.4.8 query
        profile and does not add one SELECT per message.
        """
        is_deleted_incoming_without_text = (
            bool(raw.get("deleted", False))
            and not bool(raw.get("out"))
            and not str(raw.get("text") or "").strip()
        )
        previous_body = ""
        if is_deleted_incoming_without_text:
            try:
                vk_message_id = int(raw.get("id") or 0)
            except (TypeError, ValueError):
                vk_message_id = 0
            if vk_message_id:
                existing = session.scalar(
                    select(Message).where(
                        Message.account_id == account_id,
                        Message.vk_message_id == vk_message_id,
                    )
                )
                if existing is not None:
                    previous_body = str(existing.body or "")

        message = super()._store_raw_message(
            session,
            dialog_id,
            account_id,
            raw,
            in_read=in_read,
            out_read=out_read,
        )
        if message is not None and is_deleted_incoming_without_text and previous_body.strip():
            message.body = previous_body
        return message

    async def delete_message(self, dialog_id: int, vk_message_id: int, *, delete_for_all: bool = True) -> dict:
        """Keep the dialog-card preview consistent immediately after local deletion."""
        result = await super().delete_message(
            dialog_id,
            vk_message_id,
            delete_for_all=delete_for_all,
        )
        if not result.get("ok"):
            return result

        with Session(self.engine) as session:
            dialog = session.get(Dialog, dialog_id)
            message = session.scalar(
                select(Message).where(
                    Message.dialog_id == dialog_id,
                    Message.vk_message_id == int(vk_message_id),
                )
            )
            if dialog is None or message is None:
                return result
            latest = session.scalar(
                select(Message)
                .where(Message.dialog_id == dialog_id)
                .order_by(Message.vk_message_id.desc())
                .limit(1)
            )
            is_latest = dialog.last_message_vk_id == int(vk_message_id) or (
                dialog.last_message_vk_id is None
                and latest is not None
                and latest.vk_message_id == int(vk_message_id)
            )
            if is_latest:
                dialog.last_message_vk_id = int(vk_message_id)
                dialog.last_message_deleted = True
                dialog.last_message_outgoing = bool(message.outgoing)
                dialog.last_message_preview = (
                    "" if message.outgoing else " ".join(str(message.body or "").split())
                )
                if message.sent_at is not None:
                    dialog.last_message_at = message.sent_at
                session.commit()
        return result

    async def _set_peer_notifications_best_effort(
        self,
        account_id: int,
        peer_id: int,
        *,
        enabled: bool,
    ) -> bool:
        """Change notification state only when ownership is provable.

        A generic successful mute response is not enough to set
        notifications_muted_by_app: otherwise restore could enable
        notifications the user had already disabled before archiving.
        """
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
        if not isinstance(result, VkActionResult) or result.state is not AttemptState.SENT:
            return False

        # Restore is only attempted when notifications_muted_by_app is already
        # true, so a successful unmute completes our owned state transition.
        if enabled:
            return True

        raw = result.raw if isinstance(result.raw, dict) else {}
        return raw.get("changed") is True and raw.get("previous_enabled") is True
