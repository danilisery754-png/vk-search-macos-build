from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.models import Setting
from app.services.message_variants import normalize_variants


DEFAULT_SETTINGS: dict[str, Any] = {
    "max_groups_per_account": 50,
    "delay_seconds": 60,
    "delay_mode": "fixed",
    "delay_min_seconds": 60,
    "delay_max_seconds": 90,
    "message_text": "Привет, хочу купить твоё сообщество.",
    "suggested_post_text": "Привет, хочу купить твоё сообщество.",
    "message_texts": ["Привет, хочу купить твоё сообщество."],
    "suggested_post_texts": ["Привет, хочу купить твоё сообщество."],
    "retry_min_attempts": 1,
    "retry_max_attempts": 4,
    "inbox_sync_seconds": 30,
    "ui_scale": 1.0,
    "interface_compact": False,
    "navigation_order": ["/", "/accounts", "/groups", "/inbox", "/success", "/failed", "/logs"],
}


class SettingsService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def all(self) -> dict[str, Any]:
        result = dict(DEFAULT_SETTINGS)
        stored_keys: set[str] = set()
        with Session(self.engine) as session:
            for row in session.query(Setting).all():
                result[row.key] = json.loads(row.value_json)
                stored_keys.add(row.key)
        candidates: list[str] = []
        for key in ("message_texts", "message_text", "suggested_post_texts", "suggested_post_text"):
            if key not in stored_keys:
                continue
            value = result[key]
            items = value if isinstance(value, list) else [value]
            for item in items:
                text = str(item).strip()
                if text and text not in candidates:
                    candidates.append(text)
        result["navigation_order"] = self._normalize_navigation(result.get("navigation_order"))
        shared = candidates or list(DEFAULT_SETTINGS["message_texts"])
        result["message_texts"] = shared
        result["suggested_post_texts"] = list(shared)
        result["message_text"] = shared[0]
        result["suggested_post_text"] = shared[0]
        return result

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        unknown = set(values) - set(DEFAULT_SETTINGS)
        if unknown:
            raise ValueError(f"Неизвестные настройки: {', '.join(sorted(unknown))}")
        prepared = dict(values)
        self._prepare_shared_variants(prepared)
        if "navigation_order" in prepared:
            prepared["navigation_order"] = self._normalize_navigation(prepared["navigation_order"])
        merged = self.all()
        merged.update(prepared)
        self._validate(merged)
        with Session(self.engine) as session:
            for key, value in prepared.items():
                row = session.get(Setting, key)
                encoded = json.dumps(value, ensure_ascii=False)
                if row is None:
                    session.add(Setting(key=key, value_json=encoded))
                else:
                    row.value_json = encoded
            session.commit()
        return self.all()

    @staticmethod
    def _prepare_shared_variants(values: dict[str, Any]) -> None:
        variants: list[str] | None = None
        if "message_texts" in values:
            variants = normalize_variants(values["message_texts"], "ЛС и предложки")
        elif "suggested_post_texts" in values:
            variants = normalize_variants(values["suggested_post_texts"], "ЛС и предложки")
        elif "message_text" in values or "suggested_post_text" in values:
            candidates = [values[key] for key in ("message_text", "suggested_post_text") if key in values]
            unique = list(dict.fromkeys(str(item).strip() for item in candidates))
            variants = normalize_variants(unique, "ЛС и предложки")
        if variants is None:
            return
        values["message_texts"] = variants
        values["suggested_post_texts"] = list(variants)
        values["message_text"] = variants[0]
        values["suggested_post_text"] = variants[0]

    @staticmethod
    def _normalize_navigation(value: Any) -> list[str]:
        known = list(DEFAULT_SETTINGS["navigation_order"])
        incoming = value if isinstance(value, list) else []
        result: list[str] = []
        for item in incoming:
            route = str(item)
            if route in known and route not in result:
                result.append(route)
        result.extend(route for route in known if route not in result)
        return result

    @staticmethod
    def _validate(values: dict[str, Any]) -> None:
        if "max_groups_per_account" in values and not 1 <= int(values["max_groups_per_account"]) <= 10_000:
            raise ValueError("Лимит на аккаунт должен быть от 1 до 10000")
        for key in ("delay_seconds", "delay_min_seconds", "delay_max_seconds"):
            if key in values and not 0 <= float(values[key]) <= 86_400:
                raise ValueError("Задержка должна быть от 0 до 86400 секунд")
        for key in ("retry_min_attempts", "retry_max_attempts"):
            if key in values and not 1 <= int(values[key]) <= 10:
                raise ValueError("Количество временных повторов должно быть от 1 до 10")
        if int(values.get("retry_min_attempts", 1)) > int(values.get("retry_max_attempts", 4)):
            raise ValueError("Минимум временных повторов не может быть больше максимума")
        if "ui_scale" in values and not 0.75 <= float(values["ui_scale"]) <= 3.0:
            raise ValueError("Масштаб рабочей области должен быть от 75% до 300%")
        if "inbox_sync_seconds" in values and not 5 <= float(values["inbox_sync_seconds"]) <= 3600:
            raise ValueError("Интервал синхронизации сообщений должен быть от 5 до 3600 секунд")
        for key in ("message_text", "suggested_post_text"):
            if key in values and not str(values[key]).strip():
                raise ValueError("Текст обращения не может быть пустым")
