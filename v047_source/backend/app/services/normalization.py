from __future__ import annotations

import re
from dataclasses import dataclass


_VK_URL = re.compile(
    r"(?:(?:https?://)?(?:m\.)?(?:vk\.com|vk\.ru)/)(?P<slug>[A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)
_MARKED_ID = re.compile(r"(?<![\w/.-])(?P<prefix>club|public)(?P<id>\d+)\b", re.IGNORECASE)
_PLAIN_ID = re.compile(r"(?<![\w/.-])(?P<id>\d{3,})(?![\w.-])")
_EXCLUDED_SLUGS = {
    "feed",
    "im",
    "login",
    "video",
    "videos",
    "clip",
    "clips",
    "wall",
}


@dataclass(frozen=True, slots=True)
class CommunityRef:
    raw: str
    lookup: str
    canonical_url: str


def _normalize_slug(slug: str) -> tuple[str, str] | None:
    cleaned = slug.strip(".,;:!?()[]{}<>\"'")
    lowered = cleaned.casefold()
    if not cleaned or lowered in _EXCLUDED_SLUGS:
        return None
    marked = re.fullmatch(r"(?:club|public)(\d+)", cleaned, re.IGNORECASE)
    if marked:
        community_id = marked.group(1)
        return community_id, f"https://vk.com/club{community_id}"
    if cleaned.isdigit():
        return cleaned, f"https://vk.com/club{cleaned}"
    return cleaned, f"https://vk.com/{cleaned}"


def extract_vk_community_refs(text: str) -> list[CommunityRef]:
    """Извлекает потенциальные ссылки/ID сообществ из произвольного текста.

    Screen name окончательно признаётся сообществом только после VK resolver. Здесь
    выполняется безопасная синтаксическая нормализация без сетевых запросов.
    """

    candidates: list[tuple[int, str, str]] = []
    occupied: list[tuple[int, int]] = []

    for match in _VK_URL.finditer(text or ""):
        occupied.append(match.span())
        candidates.append((match.start(), match.group(0), match.group("slug")))

    def overlaps(span: tuple[int, int]) -> bool:
        return any(span[0] < end and start < span[1] for start, end in occupied)

    for regex in (_MARKED_ID, _PLAIN_ID):
        for match in regex.finditer(text or ""):
            if overlaps(match.span()):
                continue
            candidates.append((match.start(), match.group(0), match.group("id")))

    result: list[CommunityRef] = []
    seen: set[str] = set()
    for _, raw, slug in sorted(candidates, key=lambda item: item[0]):
        normalized = _normalize_slug(slug)
        if normalized is None:
            continue
        lookup, canonical_url = normalized
        dedupe_key = lookup.casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        result.append(CommunityRef(raw=raw, lookup=lookup, canonical_url=canonical_url))
    return result

