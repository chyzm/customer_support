"""Small process-local sliding-window rate limiter."""

import asyncio
import math
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitResult:
    limit: int
    remaining: int
    reset_after: int
    allowed: bool


class InMemoryRateLimiter:
    """Count requests per authenticated client over a rolling time window.

    `time.monotonic` is immune to wall-clock changes. An asyncio lock makes the
    check-and-add operation atomic within one worker. This is deliberately a
    single-process implementation; deployment with multiple workers needs Redis
    or another shared atomic store.
    """

    def __init__(
        self,
        limit: int,
        window_seconds: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, client_id: str) -> RateLimitResult:
        async with self._lock:
            now = self._clock()
            events = self._events[client_id]
            cutoff = now - self.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()

            if len(events) >= self.limit:
                reset_after = max(1, math.ceil(self.window_seconds - (now - events[0])))
                return RateLimitResult(self.limit, 0, reset_after, False)

            events.append(now)
            remaining = self.limit - len(events)
            reset_after = max(1, math.ceil(self.window_seconds - (now - events[0])))
            return RateLimitResult(self.limit, remaining, reset_after, True)
