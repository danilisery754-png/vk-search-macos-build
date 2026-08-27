from __future__ import annotations

import hashlib


def normalize_variants(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"Варианты текста «{label}» должны быть списком")
    normalized = [str(item).strip() for item in value]
    if not normalized or any(not item for item in normalized):
        raise ValueError(f"Варианты текста «{label}» не могут содержать пустые значения")
    return normalized


def select_variant(variants: object, *, work_item_id: int, direction: str = "outreach") -> str:
    normalized = normalize_variants(variants, "обращения")
    digest = hashlib.sha256(f"{work_item_id}:outreach".encode("utf-8")).digest()
    index = int.from_bytes(digest[:8], "big") % len(normalized)
    return normalized[index]
