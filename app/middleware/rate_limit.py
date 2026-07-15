"""Small in-memory anti-spam cooldown used before database processing."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable


class CooldownRateLimiter:
    def __init__(
        self, cooldown_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._last_request: dict[int, float] = {}
        self._lock = asyncio.Lock()

    async def check(self, user_id: int) -> float:
        """Return zero when allowed, otherwise seconds until the next allowed request."""
        now = self._clock()
        async with self._lock:
            previous = self._last_request.get(user_id)
            if previous is not None:
                remaining = self.cooldown_seconds - (now - previous)
                if remaining > 0:
                    return remaining
            self._last_request[user_id] = now
        return 0.0

    async def clear(self, user_id: int) -> None:
        async with self._lock:
            self._last_request.pop(user_id, None)
