"""Per-user token bucket. The default rate is set below the GigSim limit (policy rate_limit_per_min)
so the MCP layer throttles before the platform has to."""
from __future__ import annotations

import time
from collections.abc import Callable


class RateLimited(Exception):
    def __init__(self, retry_after: float):
        super().__init__(f"rate_limited: retry after {retry_after:.1f}s")
        self.retry_after = retry_after


class TokenBucket:
    def __init__(self, rate_per_min: int, clock: Callable[[], float] = time.monotonic):
        self.capacity = float(rate_per_min)
        self.refill_per_s = rate_per_min / 60.0
        self.clock = clock
        self._state: dict[str, tuple[float, float]] = {}

    def take(self, user: str) -> None:
        now = self.clock()
        tokens, last = self._state.get(user, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - last) * self.refill_per_s)
        if tokens < 1.0:
            self._state[user] = (tokens, now)
            raise RateLimited((1.0 - tokens) / self.refill_per_s)
        self._state[user] = (tokens - 1.0, now)
