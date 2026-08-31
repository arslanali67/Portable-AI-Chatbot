"""Redis-backed rate limiter tests.

Backend-selection and fail-open tests need no live Redis and are unmarked.
Live-Redis tests require the project's Docker Redis
(`docker compose up -d redis`, see infrastructure/docker-compose.yml) and are
marked `integration`, mirroring test_database.py's Postgres convention.
"""

import logging
import time

import pytest
import redis

from app.core.config import settings
from app.core.rate_limit import InMemoryRateLimiter, RedisRateLimiter, build_rate_limiter


def test_build_rate_limiter_defaults_to_in_memory() -> None:
    limiter = build_rate_limiter(limit=1, window_seconds=1)
    assert isinstance(limiter, InMemoryRateLimiter)


def test_build_rate_limiter_selects_redis_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limiter_backend", "redis")
    limiter = build_rate_limiter(limit=1, window_seconds=1, name="test_selection")
    assert isinstance(limiter, RedisRateLimiter)


def test_build_rate_limiter_redis_requires_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limiter_backend", "redis")
    with pytest.raises(ValueError):
        build_rate_limiter(limit=1, window_seconds=1)


def test_redis_rate_limiter_fails_open_when_unreachable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    limiter = RedisRateLimiter(limit=1, window_seconds=60, name="test_fail_open")
    # Point the client at a port nothing listens on so the first command errors.
    limiter._client = redis.Redis(host="localhost", port=1, socket_connect_timeout=0.5)
    with caplog.at_level(logging.WARNING, logger="portableai.rate_limit"):
        assert limiter.allow("k") is True
    assert "failing open" in caplog.text


@pytest.mark.integration
def test_redis_rate_limiter_allows_then_blocks() -> None:
    limiter = RedisRateLimiter(limit=3, window_seconds=60, name="test_live_block")
    limiter._client.delete(f"{limiter._key_prefix}:k1", f"{limiter._key_prefix}:k2")
    assert limiter.allow("k1") is True
    assert limiter.allow("k1") is True
    assert limiter.allow("k1") is True
    assert limiter.allow("k1") is False
    # A different key is independent.
    assert limiter.allow("k2") is True


@pytest.mark.integration
def test_redis_rate_limiter_window_resets() -> None:
    limiter = RedisRateLimiter(limit=1, window_seconds=1, name="test_live_reset")
    limiter._client.delete(f"{limiter._key_prefix}:k")
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False
    time.sleep(1.1)
    assert limiter.allow("k") is True


@pytest.mark.integration
def test_redis_rate_limiter_namespaces_keys_by_name() -> None:
    """Two limiters with different `name`s must not collide on the same
    caller-supplied key, even though they share one Redis keyspace."""
    a = RedisRateLimiter(limit=1, window_seconds=60, name="test_ns_a")
    b = RedisRateLimiter(limit=1, window_seconds=60, name="test_ns_b")
    a._client.delete(f"{a._key_prefix}:shared")
    b._client.delete(f"{b._key_prefix}:shared")
    assert a.allow("shared") is True
    assert b.allow("shared") is True
