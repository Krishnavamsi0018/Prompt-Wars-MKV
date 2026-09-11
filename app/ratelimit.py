"""In-memory sliding-window rate limiter, per client IP.

Protects the free-tier Gemini quota from one client burning it. Single-instance only (no shared store) -
acceptable for the MVP; a multi-instance deployment would need Redis or the platform's rate limiting.
"""

import time
from collections import deque


class RateLimiter:
    def __init__(self, limit: int, window_s: float = 60.0) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str, now: float | None = None) -> float:
        """Record a hit. Returns 0 if allowed, otherwise seconds until the next slot frees up."""
        now = time.monotonic() if now is None else now
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            return self.window_s - (now - hits[0])
        hits.append(now)
        if len(self._hits) > 10_000:  # bound memory: drop idle clients
            self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self.window_s}
        return 0.0
