from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.enums import AttemptState
from app.vk.errors import classify_vk_error, redact_secrets


VK_API_VERSION = "5.199"
VK_API_BASE = "https://api.vk.ru/method"


def stable_random_id(idempotency_key: str) -> int:
    digest = hashlib.blake2s(idempotency_key.encode("utf-8"), digest_size=4).digest()
    value = int.from_bytes(digest, "big") & 0x7FFFFFFF
    return value or 1


@dataclass(frozen=True, slots=True)
class VkActionResult:
    state: AttemptState
    object_id: int | None = None
    error_code: int | None = None
    error_class: str = ""
    reason: str = ""
    raw: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class VkCommunity:
    vk_id: int
    screen_name: str
    name: str
    canonical_url: str
    avatar_url: str = ""


class VkApiClient:
    def __init__(
        self,
        access_token: str,
        *,
        http: httpx.AsyncClient | None = None,
        api_version: str = VK_API_VERSION,
        base_url: str = VK_API_BASE,
    ):
        if not access_token.strip():
            raise ValueError("Пустой VK-токен")
        self._token = access_token.strip()
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        self._owns_http = http is None
        self.api_version = api_version
        self.base_url = base_url.rstrip("/")

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _call(self, method: str, **params: Any) -> tuple[Any | None, VkActionResult | None]:
        form = {key: value for key, value in params.items() if value is not None}
        form.update({"access_token": self._token, "v": self.api_version})
        try:
            response = await self._http.post(f"{self.base_url}/{method}", data=form)
            if response.status_code >= 500:
                return None, VkActionResult(
                    AttemptState.TEMPORARY_ERROR,
                    error_class="http_server",
                    reason=f"Временная ошибка VK HTTP {response.status_code}.",
                )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            if isinstance(exc, httpx.ConnectTimeout):
                reason = "Таймаут подключения к VK"
            elif isinstance(exc, httpx.ReadTimeout):
                reason = "VK слишком долго не отвечал (таймаут чтения)"
            elif isinstance(exc, httpx.WriteTimeout):
                reason = "Таймаут отправки запроса в VK"
            elif isinstance(exc, httpx.PoolTimeout):
                reason = "Таймаут ожидания сетевого соединения с VK"
            else:
                reason = "Таймаут запроса к VK"
            return None, VkActionResult(
                AttemptState.TEMPORARY_ERROR,
                error_class="network_timeout",
                reason=reason,
            )
        except httpx.NetworkError as exc:
            detail = str(redact_secrets(exc, extra_values=[self._token]) or "").strip()
            if not detail:
                detail = type(exc).__name__
            return None, VkActionResult(
                AttemptState.TEMPORARY_ERROR,
                error_class="network",
                reason=f"Ошибка сети при обращении к VK: {detail}",
            )
        except (httpx.HTTPError, ValueError) as exc:
            return None, VkActionResult(
                AttemptState.UNKNOWN,
                error_class="invalid_response",
                reason=redact_secrets(exc, extra_values=[self._token]),
            )

        if "error" in payload:
            error = payload.get("error") or {}
            code = int(error.get("error_code") or 0)
            classification = classify_vk_error(code)
            api_message = redact_secrets(error.get("error_msg", ""), extra_values=[self._token])
            reason = classification.user_reason
            if api_message:
                reason = f"{reason} VK: {api_message}"
            return None, VkActionResult(
                classification.state,
                error_code=code,
                error_class=classification.category,
                reason=reason,
                raw={"error_code": code, "error_class": classification.category},
            )
        return payload.get("response"), None

    async def validate_identity(self) -> VkActionResult:
        response, error = await self._call("users.get", fields="photo_100")
        if error:
            return error
        if not isinstance(response, list) or not response:
            return VkActionResult(AttemptState.UNKNOWN, error_class="identity", reason="VK не вернул данные аккаунта.")
        user = response[0]
        deactivated = str(user.get("deactivated") or "").strip().lower()
        if deactivated == "banned":
            return VkActionResult(
                AttemptState.FAILED_FINAL,
                object_id=int(user["id"]),
                error_class="account_banned",
                reason="Аккаунт заблокирован VK.",
                raw=user,
            )
        if deactivated:
            return VkActionResult(
                AttemptState.FAILED_FINAL,
                object_id=int(user["id"]),
                error_class="account_deactivated",
                reason="Аккаунт деактивирован VK.",
                raw=user,
            )
        return VkActionResult(AttemptState.SENT, object_id=int(user["id"]), raw=user)

    async def send_community_message(
        self, community_id: int, message: str, idempotency_key: str
    ) -> VkActionResult:
        return await self.send_message(-abs(int(community_id)), message, idempotency_key)

    async def send_message(
        self,
        peer_id: int,
        message: str,
        idempotency_key: str,
        *,
        reply_to: int | None = None,
        forward: dict[str, Any] | None = None,
        attachment: str | None = None,
        sticker_id: int | None = None,
    ) -> VkActionResult:
        response, error = await self._call(
            "messages.send",
            peer_id=int(peer_id),
            message=message,
            random_id=stable_random_id(idempotency_key),
            reply_to=int(reply_to) if reply_to is not None else None,
            forward=json.dumps(forward, ensure_ascii=False, separators=(",", ":")) if forward else None,
            attachment=attachment or None,
            sticker_id=int(sticker_id) if sticker_id is not None else None,
        )
        if error:
            return error
        try:
            object_id = int(response)
        except (TypeError, ValueError):
            return VkActionResult(AttemptState.UNKNOWN, error_class="message_response", reason="VK не подтвердил ID сообщения.")
        return VkActionResult(AttemptState.SENT, object_id=object_id)

    async def edit_message(
        self, peer_id: int, *, message_id: int | None = None, conversation_message_id: int | None = None,
        message: str = "", attachment: str | None = None,
    ) -> VkActionResult:
        response, error = await self._call(
            "messages.edit",
            peer_id=int(peer_id),
            message_id=int(message_id) if message_id is not None else None,
            conversation_message_id=int(conversation_message_id) if conversation_message_id is not None else None,
            message=message,
            attachment=attachment or None,
            keep_forward_messages=1,
            keep_snippets=1,
        )
        if error:
            return error
        if response not in (1, True):
            return VkActionResult(AttemptState.UNKNOWN, error_class="message_edit_response", reason="VK не подтвердил изменение сообщения.")
        return VkActionResult(AttemptState.SENT, object_id=message_id or conversation_message_id or 1)

    async def delete_message(self, message_id: int, *, delete_for_all: bool = True) -> VkActionResult:
        response, error = await self._call(
            "messages.delete",
            message_ids=str(int(message_id)),
            delete_for_all=1 if delete_for_all else 0,
        )
        if error:
            return error
        return VkActionResult(AttemptState.SENT, object_id=int(message_id), raw=response if isinstance(response, dict) else {"response": response})

    async def set_reaction(self, peer_id: int, conversation_message_id: int, reaction_id: int) -> VkActionResult:
        response, error = await self._call(
            "messages.sendReaction",
            peer_id=int(peer_id),
            cmid=int(conversation_message_id),
            reaction_id=int(reaction_id),
        )
        if error:
            return error
        return VkActionResult(AttemptState.SENT, object_id=int(conversation_message_id), raw=response if isinstance(response, dict) else {"response": response})

    async def delete_reaction(self, peer_id: int, conversation_message_id: int) -> VkActionResult:
        response, error = await self._call(
            "messages.deleteReaction", peer_id=int(peer_id), cmid=int(conversation_message_id)
        )
        if error:
            return error
        return VkActionResult(AttemptState.SENT, object_id=int(conversation_message_id), raw=response if isinstance(response, dict) else {"response": response})

    async def get_reactions(self, peer_id: int, conversation_message_ids: list[int]):
        response, error = await self._call(
            "messages.getMessagesReactions",
            peer_id=int(peer_id),
            cmids=",".join(str(int(value)) for value in conversation_message_ids),
        )
        return response, error

    async def set_activity(self, peer_id: int, activity: str = "typing") -> VkActionResult:
        response, error = await self._call("messages.setActivity", peer_id=int(peer_id), type=activity)
        if error:
            return error
        if response not in (1, True):
            return VkActionResult(AttemptState.UNKNOWN, error_class="activity_response", reason="VK не подтвердил статус набора сообщения.")
        return VkActionResult(AttemptState.SENT, object_id=1)

    async def get_history_attachments(self, peer_id: int, *, media_type: str = "photo", start_from: str | None = None, count: int = 100):
        response, error = await self._call(
            "messages.getHistoryAttachments",
            peer_id=int(peer_id),
            media_type=media_type,
            start_from=start_from,
            count=min(max(count, 1), 200),
            photo_sizes=1,
        )
        return response, error

    async def search_messages(self, query: str, *, peer_id: int | None = None, count: int = 100):
        response, error = await self._call(
            "messages.search", q=query, peer_id=int(peer_id) if peer_id is not None else None, count=min(max(count, 1), 100)
        )
        return response, error

    async def get_long_poll_server(self, *, need_pts: bool = True, lp_version: int = 3):
        response, error = await self._call(
            "messages.getLongPollServer", need_pts=1 if need_pts else 0, lp_version=int(lp_version)
        )
        return response, error

    async def send_suggested_post(self, community_id: int, message: str) -> VkActionResult:
        response, error = await self._call(
            "wall.post",
            owner_id=-abs(int(community_id)),
            message=message,
        )
        if error:
            return error
        if not isinstance(response, dict) or "post_id" not in response:
            return VkActionResult(AttemptState.UNKNOWN, error_class="wall_response", reason="VK не подтвердил ID записи.")
        return VkActionResult(AttemptState.SENT, object_id=int(response["post_id"]))

    async def get_conversations(self, *, offset: int = 0, count: int = 100, unread_only: bool = False):
        response, error = await self._call(
            "messages.getConversations",
            offset=offset,
            count=min(max(count, 1), 200),
            filter="unread" if unread_only else "all",
            extended=1,
        )
        return response, error

    async def get_history(self, peer_id: int, *, offset: int = 0, count: int = 100):
        response, error = await self._call(
            "messages.getHistory", peer_id=peer_id, offset=offset, count=min(max(count, 1), 200)
        )
        return response, error

    async def mark_as_read(self, peer_id: int, *, start_message_id: int | None = None) -> VkActionResult:
        response, error = await self._call(
            "messages.markAsRead",
            peer_id=int(peer_id),
            start_message_id=start_message_id,
        )
        if error:
            return error
        if response not in (1, True):
            return VkActionResult(
                AttemptState.UNKNOWN,
                error_class="mark_read_response",
                reason="VK не подтвердил отметку сообщений прочитанными.",
            )
        return VkActionResult(AttemptState.SENT, object_id=1)

    async def resolve_communities(self, lookups: list[str]) -> tuple[list[VkCommunity], VkActionResult | None]:
        if not lookups:
            return [], None
        response, error = await self._call(
            "groups.getById",
            group_ids=",".join(lookups[:500]),
            fields="photo_100,screen_name",
        )
        if error:
            return [], error
        raw_groups = response.get("groups", []) if isinstance(response, dict) else response
        if not isinstance(raw_groups, list):
            return [], VkActionResult(
                AttemptState.UNKNOWN,
                error_class="groups_response",
                reason="VK вернул неизвестный формат данных сообществ.",
            )
        groups: list[VkCommunity] = []
        for raw in raw_groups:
            try:
                vk_id = abs(int(raw["id"]))
            except (KeyError, TypeError, ValueError):
                continue
            screen_name = str(raw.get("screen_name") or f"club{vk_id}")
            groups.append(
                VkCommunity(
                    vk_id=vk_id,
                    screen_name=screen_name,
                    name=str(raw.get("name", "")),
                    canonical_url=f"https://vk.com/{screen_name}",
                    avatar_url=str(raw.get("photo_100", "")),
                )
            )
        return groups, None
