from __future__ import annotations

import asyncio
import math
import time
from collections import defaultdict, deque

from fastapi import HTTPException, status


class FixedWindowRateLimiter:
    """Small process-local limiter; keying never trusts forwarded client headers."""

    def __init__(self, window_seconds: int) -> None:
        self._window = window_seconds
        self._events: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, scope: str, identity: str, limit: int) -> None:
        now = time.monotonic()
        key = f"{scope}:{identity}"
        async with self._lock:
            events = self._events[key]
            while events and events[0] <= now - self._window:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, math.ceil(self._window - (now - events[0])))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(retry_after)},
                )
            events.append(now)
