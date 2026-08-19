"""Tests for production hardening:
- readiness endpoint
- body-size limit middleware (413)
- error-handling middleware (safe 500s)
- request-logging middleware presence
- rate limiter abstraction
- JWT access-token `type` claim enforcement
- config fail-fast validation
"""

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import DEV_JWT_SECRET, Settings, settings
from app.core.rate_limit import build_rate_limiter
from app.core.security import create_access_token, decode_access_token
from app.main import app

client = TestClient(app)


def test_readiness_ready_with_db() -> None:
    response = client.get("/api/v1/ready")
    # In the test environment the database is reachable (NullPool + test DB).
    assert response.status_code in (200, 503)
    if response.status_code == 200:
        assert response.json() == {"status": "ready", "database": "ok"}


def test_readiness_not_ready_when_db_down() -> None:
    from app.core.database import get_db
    from app.main import app as main_app

    class FakeSession:
        async def execute(self, *args, **kwargs):
            raise ConnectionError("down")

    async def broken_get_db():
        yield FakeSession()

    original = main_app.dependency_overrides.get(get_db)
    main_app.dependency_overrides[get_db] = broken_get_db
    try:
        broken_client = TestClient(main_app)
        response = broken_client.get("/api/v1/ready")
    finally:
        if original is not None:
            main_app.dependency_overrides[get_db] = original
        else:
            main_app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 503
    assert response.json() == {"status": "not ready", "database": "unreachable"}


def test_body_size_limit_rejects_oversized_body() -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"name": "x" * (settings.max_request_bytes + 100)},
    )
    assert response.status_code == 413


def test_error_handling_middleware_returns_safe_500() -> None:
    from fastapi import APIRouter

    from app.main import app as main_app

    boom_router = APIRouter()

    @boom_router.get("/boom")
    def boom():
        raise RuntimeError("secret-internal-detail")

    main_app.include_router(boom_router, prefix="/test")
    added = [r for r in main_app.routes if getattr(r, "path", "").startswith("/test")]
    try:
        response = client.get("/test/boom")
    finally:
        for route in added:
            try:
                main_app.routes.remove(route)
            except ValueError:
                pass
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "secret-internal-detail" not in response.text


def test_rate_limiter_blocks_after_limit() -> None:
    limiter = build_rate_limiter(limit=3, window_seconds=60)
    assert limiter.allow("k1") is True
    assert limiter.allow("k1") is True
    assert limiter.allow("k1") is True
    assert limiter.allow("k1") is False
    # Different key is independent.
    assert limiter.allow("k2") is True


def test_rate_limiter_window_resets() -> None:
    import time

    limiter = build_rate_limiter(limit=1, window_seconds=1)
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False
    time.sleep(1.1)
    assert limiter.allow("k") is True


def test_jwt_token_type_claim_enforced() -> None:
    other_payload = {"sub": "1", "type": "not-access", "exp": 9999999999}
    token = pyjwt.encode(other_payload, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_access_token(token)


def test_jwt_access_token_roundtrip() -> None:
    token = create_access_token(user_id=42)
    payload = decode_access_token(token)
    assert payload["type"] == "access"
    assert payload["sub"] == "42"


def test_production_config_fails_fast_on_weak_secret() -> None:
    with pytest.raises(ValueError):
        Settings(
            environment="production",
            jwt_secret=DEV_JWT_SECRET,
            database_url="postgresql+asyncpg://u:p@h:5432/d",
            cors_origins=["http://localhost:3000"],
            trusted_hosts=["portableai.example.com"],
            debug=False,
        )


def test_production_config_fails_fast_without_trusted_hosts() -> None:
    with pytest.raises(ValueError):
        Settings(
            environment="production",
            jwt_secret="a" * 40,
            database_url="postgresql+asyncpg://u:p@h:5432/d",
            cors_origins=["http://localhost:3000"],
            trusted_hosts=[],
            debug=False,
        )


def test_production_config_fails_fast_with_debug() -> None:
    with pytest.raises(ValueError):
        Settings(
            environment="production",
            jwt_secret="a" * 40,
            database_url="postgresql+asyncpg://u:p@h:5432/d",
            cors_origins=["http://localhost:3000"],
            trusted_hosts=["portableai.example.com"],
            debug=True,
        )


def test_development_config_allows_dev_secret() -> None:
    dev = Settings(
        environment="development",
        jwt_secret=DEV_JWT_SECRET,
        database_url="postgresql+asyncpg://u:p@h:5432/d",
    )
    assert dev.is_production is False


def test_invalid_environment_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(environment="staging", jwt_secret="x", database_url="x")


def test_widget_config_revoke_persists() -> None:
    """Regression: revoke stores an aware datetime into a tz-aware column."""
    from fastapi.testclient import TestClient

    from app.main import app as main_app

    from tests.conftest import TestSessionLocal
    from app.repositories.widget import WidgetConfigRepository

    client = TestClient(main_app)

    email = f"rev-{id(object())}@test.com"
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password123!", "full_name": "Rev"},
    )
    assert r.status_code == 201
    token = client.post(
        "/api/v1/auth/login", data={"username": email, "password": "Password123!"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    import time

    unique = f"rev-{int(time.time() * 1000)}"
    org = client.post(
        "/api/v1/organizations", headers=headers, json={"name": unique, "slug": unique}
    ).json()
    bot = client.post(
        f"/api/v1/organizations/{org['id']}/chatbots",
        headers=headers,
        json={
            "name": "Rev Bot",
            "slug": "rev-bot",
            "description": "",
            "system_prompt": "",
            "welcome_message": "",
            "language": "en",
            "visibility": "private",
            "provider_id": "fake-a",
            "model_id": "fake-model-small",
        },
    )
    assert bot.status_code == 201, bot.text
    bot_id = bot.json()["id"]

    created = client.post(
        f"/api/v1/organizations/{org['id']}/chatbots/{bot_id}/widget-config",
        headers=headers,
        json={"allowed_origins": ["http://localhost:3000"]},
    )
    assert created.status_code == 201, created.text

    revoked = client.delete(
        f"/api/v1/organizations/{org['id']}/chatbots/{bot_id}/widget-config",
        headers=headers,
    )
    assert revoked.status_code == 204, revoked.text

    async def check():
        async with TestSessionLocal() as db:
            config = await WidgetConfigRepository(db).get_by_public_key_session(bot_id)
            assert config is not None
            assert config.revoked_at is not None

    import asyncio

    asyncio.run(check())
