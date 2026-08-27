from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Hashable, Iterable


@dataclass(frozen=True, slots=True)
class AccountCapacity:
    account_id: int
    limit: int
    enabled: bool = True


def distribute_balanced(
    group_ids: Iterable[Hashable],
    accounts: Iterable[AccountCapacity],
    *,
    seed: int | None = None,
) -> dict[Hashable, int]:
    """Случайно перемешивает группы и равномерно назначает их аккаунтам.

    Лимит применяется отдельно к каждому аккаунту. Порядок аккаунтов сохраняется,
    что делает алгоритм воспроизводимым при фиксированном seed.
    """

    active = [item for item in accounts if item.enabled and item.limit > 0]
    if not active:
        return {}
    groups = list(dict.fromkeys(group_ids))
    random.Random(seed).shuffle(groups)
    assigned_count = {item.account_id: 0 for item in active}
    result: dict[Hashable, int] = {}
    cursor = 0

    for group_id in groups:
        chosen: AccountCapacity | None = None
        for offset in range(len(active)):
            candidate = active[(cursor + offset) % len(active)]
            if assigned_count[candidate.account_id] < candidate.limit:
                chosen = candidate
                cursor = (cursor + offset + 1) % len(active)
                break
        if chosen is None:
            break
        result[group_id] = chosen.account_id
        assigned_count[chosen.account_id] += 1
    return result

