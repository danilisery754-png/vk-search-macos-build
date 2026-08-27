from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 4
    base_seconds: float = 5.0
    max_seconds: float = 120.0
    jitter_ratio: float = 0.2

    def delay_for(self, attempt: int, *, rng: random.Random | None = None) -> float | None:
        if attempt < 1:
            raise ValueError("Номер попытки начинается с 1")
        if attempt > self.max_attempts:
            return None
        raw = min(self.max_seconds, self.base_seconds * (2 ** (attempt - 1)))
        if self.jitter_ratio <= 0:
            return raw
        generator = rng or random
        spread = raw * self.jitter_ratio
        return max(0.0, generator.uniform(raw - spread, raw + spread))

