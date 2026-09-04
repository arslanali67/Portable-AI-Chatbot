"""BYOK AI provider credential tests — CRUD, save-time validation, masking,
permission, encryption-at-rest, and log safety.

Require Docker PostgreSQL + alembic upgrade head. Run: pytest -m identity
"""

import asyncio
import logging
import uuid

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from httpx import AsyncClient, Response
from sqlalchemy import text

from app.ai.capabilities import AICapability
from app.ai.metadata import ModelMetadata, ProviderMetadata
from app.ai.providers.openai_compatible import OpenAICompatibleHTTPProvider
from app.ai.registry import model_registry, provider_registry
from app.core.config import settings
from app.main import app
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.identity

client = TestClient(app)

PASSWORD = "Strong-password-123"
_RUN = uuid.uuid4().hex[:8]

TEST_PROVIDER_ID = "byok-test"
TEST_MODEL_ID = "byok-test-model"
VALID_KEY = "valid-key-123"


class KeyCheckTransport:
    """Mock HTTP transport: 200 only for the configured valid key, else 401."""

    def __init__(self, valid_key: str) -> None:
        self.valid_key = valid_key
        self.requests: list = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        if request.headers.get("authorization") == f"Bearer {self.valid_key}":
            return Response(
                200,
                json={
                    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )
        return Response(401, json={"error": {"message": "invalid api key"}})


@pytest.fixture(autouse=True)
def _test_provider():
    """Registers a throwaway OpenAI-compatible provider whose mock transport
    only accepts VALID_KEY — lets save-time validation genuinely succeed/fail
    without a real network call. Reaches into the registries' private dicts
    to add/remove, mirroring this suite's existing gateway-swap convention."""
    transport = KeyCheckTransport(VALID_KEY)
    provider = OpenAICompatibleHTTPProvider(
        ProviderMetadata(
            provider_id=TEST_PROVIDER_ID,
            display_name="BYOK Test Provider",
            description="test",
            enabled=True,
            base_url="https://mock.test/v1",
            authentication_type="api_key",
            compatibility_type="openai_compatible",
            capabilities={AICapability.TEXT_GENERATION},
        ),
        api_key="unused-default-key",
        base_url="https://mock.test/v1",
        timeout=5.0,
        client=AsyncClient(transport=transport),
    )
    model = ModelMetadata(
        provider_id=TEST_PROVIDER_ID,
        model_id=TEST_MODEL_ID,
        display_name="Test Model",
        context_window=1000,
        max_output_tokens=100,
        enabled=True,
        capabilities={AICapability.TEXT_GENERATION},
    )
    provider_registry._providers[TEST_PROVIDER_ID] = provider
    model_registry._models[(TEST_PROVIDER_ID, TEST_MODEL_ID)] = model
    yield transport
    provider_registry._providers.pop(TEST_PROVIDER_ID, None)
    model_registry._models.pop((TEST_PROVIDER_ID, TEST_MODEL_ID), None)


def _email(name: str) -> str:
    return f"{name}-{_RUN}@example.com"


def _slug(name: str) -> str:
    return f"{name}-{_RUN}"


def _register(email: str, full_name: str = "Cred Tester"):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": full_name},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _login(email: str) -> str:
    r = client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_org(token: str, name: str, slug: str) -> int:
    r = client.post(
        "/api/v1/organizations", json={"name": name, "slug": slug}, headers=_auth(token)
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _set_role(user_email: str, org_id: int, role: str) -> None:
    async with TestSessionLocal() as s:
        await s.execute(
            text(
                "INSERT INTO memberships (user_id, organization_id, role) "
                "SELECT id, :oid, :role FROM users WHERE email = :email "
                "ON CONFLICT (user_id, organization_id) DO UPDATE SET role = EXCLUDED.role"
            ),
            {"role": role, "oid": org_id, "email": user_email},
        )
        await s.commit()


def _setup_owner() -> tuple[str, int]:
    email = _email(f"owner{uuid.uuid4().hex[:6]}")
    token = _login(_register(email)["email"])
    org_id = _create_org(token, "Org", _slug(f"org{uuid.uuid4().hex[:6]}"))
    return token, org_id


def _setup_member(org_id: int) -> str:
    email = _email(f"member{uuid.uuid4().hex[:6]}")
    _register(email)
    token = _login(email)
    asyncio.run(_set_role(email, org_id, "member"))
    return token


async def _raw_encrypted_key(org_id: int, provider_id: str) -> bytes | None:
    async with TestSessionLocal() as s:
        r = await s.execute(
            text(
                "SELECT encrypted_key FROM ai_provider_credentials "
                "WHERE organization_id = :oid AND provider_id = :pid"
            ),
            {"oid": org_id, "pid": provider_id},
        )
        row = r.first()
        return bytes(row[0]) if row else None


def _set_credential(token: str, org_id: int, provider_id: str, api_key: str):
    return client.put(
        f"/api/v1/organizations/{org_id}/ai-credentials/{provider_id}",
        json={"api_key": api_key},
        headers=_auth(token),
    )


def _list_credentials(token: str, org_id: int):
    return client.get(f"/api/v1/organizations/{org_id}/ai-credentials", headers=_auth(token))


def _delete_credential(token: str, org_id: int, provider_id: str):
    return client.delete(
        f"/api/v1/organizations/{org_id}/ai-credentials/{provider_id}", headers=_auth(token)
    )


# --- Save (valid key): succeeds, encrypted at rest, masked response ---


def test_set_valid_key_succeeds_and_is_encrypted_at_rest() -> None:
    token, org_id = _setup_owner()
    r = _set_credential(token, org_id, TEST_PROVIDER_ID, VALID_KEY)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider_id"] == TEST_PROVIDER_ID
    assert body["masked_key"] == "••••••••" + VALID_KEY[-4:]
    assert VALID_KEY not in str(body)

    raw = asyncio.run(_raw_encrypted_key(org_id, TEST_PROVIDER_ID))
    assert raw is not None
    assert raw != VALID_KEY.encode()
    assert VALID_KEY.encode() not in raw
    # Round-trips back to the original plaintext through the real app key.
    fernet = Fernet(settings.ai_credential_encryption_key.encode())
    assert fernet.decrypt(raw).decode() == VALID_KEY


def test_list_shows_masked_and_updated_by() -> None:
    token, org_id = _setup_owner()
    _set_credential(token, org_id, TEST_PROVIDER_ID, VALID_KEY)
    r = _list_credentials(token, org_id)
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["provider_id"] == TEST_PROVIDER_ID
    assert items[0]["masked_key"].startswith("••••••••")
    assert items[0]["updated_by_email"] is not None


# --- Save (invalid key): rejected, 4xx, nothing persisted ---


def test_set_invalid_key_rejected_and_nothing_persisted() -> None:
    token, org_id = _setup_owner()
    r = _set_credential(token, org_id, TEST_PROVIDER_ID, "wrong-key-000")
    assert 400 <= r.status_code < 500, r.text
    assert asyncio.run(_raw_encrypted_key(org_id, TEST_PROVIDER_ID)) is None
    assert _list_credentials(token, org_id).json() == []


def test_set_unknown_provider_404() -> None:
    token, org_id = _setup_owner()
    r = _set_credential(token, org_id, "totally-unknown-provider", VALID_KEY)
    assert r.status_code == 404


# --- Permission: MEMBER cannot set/view/remove ---


def test_member_cannot_set_view_or_remove_credential() -> None:
    token, org_id = _setup_owner()
    _set_credential(token, org_id, TEST_PROVIDER_ID, VALID_KEY)
    member_token = _setup_member(org_id)

    assert _set_credential(member_token, org_id, TEST_PROVIDER_ID, VALID_KEY).status_code == 403
    assert _list_credentials(member_token, org_id).status_code == 403
    assert _delete_credential(member_token, org_id, TEST_PROVIDER_ID).status_code == 403


# --- Remove clears the row ---


def test_remove_credential_clears_row() -> None:
    token, org_id = _setup_owner()
    _set_credential(token, org_id, TEST_PROVIDER_ID, VALID_KEY)
    assert asyncio.run(_raw_encrypted_key(org_id, TEST_PROVIDER_ID)) is not None

    r = _delete_credential(token, org_id, TEST_PROVIDER_ID)
    assert r.status_code == 204
    assert asyncio.run(_raw_encrypted_key(org_id, TEST_PROVIDER_ID)) is None
    assert _list_credentials(token, org_id).json() == []


def test_remove_nonexistent_credential_404() -> None:
    token, org_id = _setup_owner()
    assert _delete_credential(token, org_id, TEST_PROVIDER_ID).status_code == 404


# --- Plaintext never logged ---


def test_plaintext_key_never_appears_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    token, org_id = _setup_owner()
    with caplog.at_level(logging.DEBUG):
        _set_credential(token, org_id, TEST_PROVIDER_ID, VALID_KEY)
        _list_credentials(token, org_id)
        _delete_credential(token, org_id, TEST_PROVIDER_ID)
    assert VALID_KEY not in caplog.text
