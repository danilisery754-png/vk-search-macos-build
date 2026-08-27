from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Setting
from app.services.message_variants import normalize_variants, select_variant
from app.services.settings import SettingsService


def make_service(tmp_path) -> SettingsService:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'settings.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return SettingsService(engine)


def test_normalize_variants_trims_text_without_limiting_count():
    values = [f" Вариант {index} " for index in range(250)]

    normalized = normalize_variants(values, "ЛС")

    assert normalized == [f"Вариант {index}" for index in range(250)]


@pytest.mark.parametrize("value", [[], [""], ["Первый", "   "]])
def test_normalize_variants_rejects_empty_entries(value):
    with pytest.raises(ValueError, match="пуст"):
        normalize_variants(value, "ЛС")


def test_legacy_scalar_is_loaded_as_the_first_variant(tmp_path):
    service = make_service(tmp_path)
    with Session(service.engine) as session:
        session.add(Setting(key="message_text", value_json=json.dumps("Старый текст", ensure_ascii=False)))
        session.add(Setting(key="suggested_post_text", value_json=json.dumps("Текст предложки", ensure_ascii=False)))
        session.commit()

    values = service.all()

    assert values["message_text"] == "Старый текст"
    assert values["message_texts"] == ["Старый текст", "Текст предложки"]
    assert values["suggested_post_texts"] == values["message_texts"]


def test_saving_variants_keeps_legacy_scalar_compatible(tmp_path):
    service = make_service(tmp_path)

    values = service.update({"message_texts": [" Первый ", "Второй"]})

    assert values["message_texts"] == ["Первый", "Второй"]
    assert values["message_text"] == "Первый"
    assert values["suggested_post_texts"] == ["Первый", "Второй"]
    assert values["suggested_post_text"] == "Первый"
    with Session(service.engine) as session:
        stored = session.get(Setting, "message_texts")
        legacy = session.get(Setting, "message_text")
        suggested_stored = session.get(Setting, "suggested_post_texts")
        suggested_legacy = session.get(Setting, "suggested_post_text")
    assert json.loads(stored.value_json) == ["Первый", "Второй"]
    assert json.loads(legacy.value_json) == "Первый"
    assert json.loads(suggested_stored.value_json) == ["Первый", "Второй"]
    assert json.loads(suggested_legacy.value_json) == "Первый"


def test_variant_selection_is_stable_and_distributes_work_items():
    values = ["Первый", "Второй", "Третий"]

    same = {select_variant(values, work_item_id=41, direction="message") for _ in range(10)}
    distributed = {select_variant(values, work_item_id=item_id, direction="message") for item_id in range(1, 50)}

    assert len(same) == 1
    assert distributed == {"Первый", "Второй", "Третий"}


def test_variant_selection_is_shared_between_both_delivery_directions():
    values = [f"Вариант {index}" for index in range(20)]

    message = select_variant(values, work_item_id=7, direction="message")
    suggested = select_variant(values, work_item_id=7, direction="suggested")

    assert message == suggested
