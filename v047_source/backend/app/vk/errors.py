from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.enums import AttemptState


@dataclass(frozen=True, slots=True)
class ErrorClassification:
    state: AttemptState
    category: str
    user_reason: str


_ERRORS: dict[int, ErrorClassification] = {
    5: ErrorClassification(AttemptState.AUTH_REQUIRED, "authorization", "Требуется повторный вход в аккаунт."),
    6: ErrorClassification(AttemptState.TEMPORARY_ERROR, "rate_limit", "VK временно ограничил частоту запросов."),
    9: ErrorClassification(AttemptState.TEMPORARY_ERROR, "flood_control", "VK временно ограничил слишком частые действия."),
    10: ErrorClassification(AttemptState.TEMPORARY_ERROR, "vk_internal", "Временная внутренняя ошибка VK."),
    14: ErrorClassification(AttemptState.AUTH_REQUIRED, "captcha", "VK запросил дополнительное подтверждение."),
    15: ErrorClassification(AttemptState.FAILED_FINAL, "access_denied", "У аккаунта нет доступа к этому действию."),
    18: ErrorClassification(AttemptState.FAILED_FINAL, "community_unavailable", "Сообщество удалено или недоступно."),
    100: ErrorClassification(AttemptState.FAILED_FINAL, "invalid_request", "VK отклонил параметры действия."),
    214: ErrorClassification(AttemptState.FAILED_FINAL, "suggested_post_forbidden", "Предложенные записи в этом сообществе недоступны или запрещены."),
    900: ErrorClassification(AttemptState.FAILED_FINAL, "message_restricted", "Отправка сообщения ограничена настройками получателя."),
    901: ErrorClassification(AttemptState.FAILED_FINAL, "message_forbidden", "Этот аккаунт не может отправить сообщение сообществу."),
    902: ErrorClassification(AttemptState.FAILED_FINAL, "community_messages_unavailable", "Сообщество не принимает это сообщение."),
}


def classify_vk_error(code: int) -> ErrorClassification:
    return _ERRORS.get(
        int(code),
        ErrorClassification(AttemptState.UNKNOWN, "unknown", f"VK вернул неподтверждённую ошибку {code}."),
    )


_TOKEN_FIELD = re.compile(
    r"(?i)([\"']?(?:access_token|token)[\"']?\s*(?:[=:]|%3[dD])\s*[\"']?)([^\s&\"',}]+)",
)
_TOKEN_QUERY = re.compile(r"(?i)(access_token=)([^&#\s]+)")


def redact_secrets(value: object, *, extra_values: list[str] | tuple[str, ...] = ()) -> str:
    text = str(value)
    text = _TOKEN_FIELD.sub(lambda match: f"{match.group(1)}[СКРЫТО]", text)
    text = _TOKEN_QUERY.sub(r"\1[СКРЫТО]", text)
    for secret in sorted((item for item in extra_values if item), key=len, reverse=True):
        text = text.replace(secret, "[СКРЫТО]")
    return text
