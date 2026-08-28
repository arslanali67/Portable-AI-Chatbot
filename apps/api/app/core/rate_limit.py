"""Rate limiter abstraction for public endpoints.

Routes depend on the `RateLimiter` protocol only, never a concrete backend.
The default backend is in-memory (process-local) — documented MVP trade-off,
not safe for multi-instance production. A Redis-backed backend can be added
without changing routes.
"""

import time
from collections import defaultdict, deque
from typing import Protocol


class RateLimiter(Protocol):
    """Protocol: a rate limiter keyed by a string. Returns True if allowed."""

    limit: int
    window_seconds: int

    def allow(self, key: str) -> bool: ...


class InMemoryRateLimiter:
    """Sliding-window in-memory rate limiter (process-local)."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        queue = self._hits[key]
        while queue and now - queue[0] > self.window_seconds:
            queue.popleft()
        if len(queue) >= self.limit:
            return False
        queue.append(now)
        return True


def build_rate_limiter(limit: int, window_seconds: int) -> RateLimiter:
    """Factory for limiter backends.

    Currently returns the in-memory implementation. A future Redis-backed
    implementation can be selected here without changing call sites.
    """
    return InMemoryRateLimiter(limit=limit, window_seconds=window_seconds)


widget_rate_limiter: RateLimiter = build_rate_limiter(limit=30, window_seconds=3600)

# Per-IP limiter with generous ceiling (MVP; process-local).
widget_ip_rate_limiter: RateLimiter = build_rate_limiter(limit=1000, window_seconds=3600)

# Password-reset request limiters — same dual per-key/per-IP shape as the
# widget limiters above, reusing the same abstraction (no new mechanism).
password_reset_email_rate_limiter: RateLimiter = build_rate_limiter(limit=5, window_seconds=3600)
password_reset_ip_rate_limiter: RateLimiter = build_rate_limiter(limit=20, window_seconds=3600)