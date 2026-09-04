"""Rate limiter abstraction for public endpoints.

Routes depend on the `RateLimiter` protocol only, never a concrete backend.
The default backend is in-memory (process-local) — safe for a single
instance, silently N-times-looser than configured across N instances. A
Redis-backed backend is available (settings.rate_limiter_backend = "redis")
for multi-instance deployments; selecting it requires no route changes.
"""

import logging
import time
from collections import defaultdict, deque
from typing import Protocol

import redis

from app.core.config import settings

logger = logging.getLogger("portableai.rate_limit")


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


# Single shared connection pool for the Redis backend, mirroring how the DB
# engine (app/core/database.py) is a module-level singleton with no explicit
# startup/shutdown hook — the client lazily connects on first command.
_redis_pool = redis.ConnectionPool.from_url(settings.redis_url)


class RedisRateLimiter:
    """Fixed-window rate limiter backed by Redis: INCR + EXPIRE (set only on
    the first hit in a window). Matches the coarse abuse-prevention precision
    the existing limiters actually need — not a sorted-set sliding window.

    Fails open: any connection/command error is logged at WARNING and treated
    as "allowed". Rate limiting is an abuse-prevention control, not an
    authorization control — a Redis outage must degrade to "no rate
    limiting", never to an unrelated endpoint returning 500 or 429.
    """

    def __init__(self, limit: int, window_seconds: int, name: str) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._key_prefix = f"ratelimit:{name}"
        self._client = redis.Redis(connection_pool=_redis_pool)

    def allow(self, key: str) -> bool:
        redis_key = f"{self._key_prefix}:{key}"
        try:
            count = self._client.incr(redis_key)
            if count == 1:
                self._client.expire(redis_key, self.window_seconds)
        except redis.RedisError as exc:
            logger.warning("Redis rate limiter unreachable, failing open: %s", exc)
            return True
        return count <= self.limit


def build_rate_limiter(
    limit: int, window_seconds: int, *, name: str | None = None
) -> RateLimiter:
    """Factory for limiter backends, selected via settings.rate_limiter_backend.

    `name` namespaces this limiter's keys in the shared Redis keyspace — two
    different limiters must never collide on the same underlying key (e.g. a
    raw IP or email address reused as a key by more than one limiter).
    Required only when the redis backend is actually selected; ignored by the
    in-memory backend, which is isolated by Python object identity already.
    """
    if settings.rate_limiter_backend == "redis":
        if not name:
            raise ValueError(
                "build_rate_limiter(..., name=...) is required when "
                "rate_limiter_backend is 'redis', to namespace Redis keys"
            )
        return RedisRateLimiter(limit=limit, window_seconds=window_seconds, name=name)
    return InMemoryRateLimiter(limit=limit, window_seconds=window_seconds)


widget_rate_limiter: RateLimiter = build_rate_limiter(
    limit=30, window_seconds=3600, name="widget_session"
)

# Per-IP limiter with generous ceiling (MVP; process-local).
widget_ip_rate_limiter: RateLimiter = build_rate_limiter(
    limit=1000, window_seconds=3600, name="widget_ip"
)

# Password-reset request limiters — same dual per-key/per-IP shape as the
# widget limiters above, reusing the same abstraction (no new mechanism).
password_reset_email_rate_limiter: RateLimiter = build_rate_limiter(
    limit=5, window_seconds=3600, name="pwreset_email"
)
password_reset_ip_rate_limiter: RateLimiter = build_rate_limiter(
    limit=20, window_seconds=3600, name="pwreset_ip"
)

# Crawl ingestion costs far more than a single-URL ingest (up to
# max_crawl_pages fetches/embeds per request) — limited per organization.
crawl_rate_limiter: RateLimiter = build_rate_limiter(
    limit=settings.crawl_rate_limit_per_hour, window_seconds=3600, name="crawl"
)
