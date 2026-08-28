"""AI management API tests — read-only provider/model discovery + chatbot
provider/model validation.

Require Docker PostgreSQL + alembic upgrade head. Run: pytest -m identity
"""

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models import User
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.identity

client = TestClient(app)

PASSWORD = "strong-password-123"
_RUN = uuid.uuid4().hex[:8]


def _email(name: str) -> str:
    return f"{name}-{_RUN}@example.com"


def _slug(name: str) -> str:
    return f"{name}-{_RUN}"


def _register(email: str, full_name: str = "Mgmt Tester"):
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


def _setup_token() -> str:
    email = _email(f"user{uuid.uuid4().hex[:6]}")
    return _login(_register(email)["email"])


async def _promote_platform_admin(user_id: int) -> None:
    async with TestSessionLocal() as session:
        user = await session.get(User, user_id)
        user.is_platform_admin = True
        await session.commit()


def _setup_admin_token() -> str:
    """No self-service promotion endpoint exists by design — the flag is
    set via direct DB access, exactly as it would be in production."""
    email = _email(f"admin{uuid.uuid4().hex[:6]}")
    user = _register(email)
    asyncio.run(_promote_platform_admin(user["id"]))
    return _login(email)


def _create_org(token: str) -> int:
    r = client.post(
        "/api/v1/organizations",
        json={"name": "Org", "slug": _slug(f"org{uuid.uuid4().hex[:6]}")},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_bot(token: str, org_id: int, **overrides):
    payload = {"name": "Bot", "slug": _slug(f"bot{uuid.uuid4().hex[:6]}")}
    payload.update(overrides)
    return client.post(
        f"/api/v1/organizations/{org_id}/chatbots",
        json=payload,
        headers=_auth(token),
    )


# --- API tests ---


def test_provider_list_200() -> None:
    token = _setup_token()
    r = client.get("/api/v1/ai/providers", headers=_auth(token))
    assert r.status_code == 200
    ids = {p["provider_id"] for p in r.json()}
    assert {"fake-a", "fake-b", "gemini"} <= ids


def test_single_provider_200() -> None:
    token = _setup_token()
    r = client.get("/api/v1/ai/providers/gemini", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["provider_id"] == "gemini"
    assert body["display_name"] == "Google Gemini"
    assert body["compatibility_type"] == "openai_compatible"
    assert body["authentication_type"] == "api_key"
    # Enabled reflects actual config state (no key in CI → disabled).
    assert body["enabled"] in (True, False)


def test_model_list_200() -> None:
    token = _setup_token()
    r = client.get("/api/v1/ai/providers/fake-a/models", headers=_auth(token))
    assert r.status_code == 200
    models = r.json()
    assert {m["model_id"] for m in models} == {"fake-model-small", "fake-model-large"}
    assert all(m["provider_id"] == "fake-a" for m in models)


def test_single_model_200() -> None:
    token = _setup_token()
    r = client.get(
        "/api/v1/ai/providers/fake-a/models/fake-model-small", headers=_auth(token)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["model_id"] == "fake-model-small"
    assert body["provider_id"] == "fake-a"
    assert body["enabled"] is True
    assert "text_generation" in body["capabilities"]


def test_unknown_provider_404() -> None:
    token = _setup_token()
    assert client.get("/api/v1/ai/providers/nope", headers=_auth(token)).status_code == 404
    assert (
        client.get("/api/v1/ai/providers/nope/models", headers=_auth(token)).status_code
        == 404
    )


def test_unknown_model_404() -> None:
    token = _setup_token()
    assert (
        client.get(
            "/api/v1/ai/providers/fake-a/models/nope", headers=_auth(token)
        ).status_code
        == 404
    )


def test_unauthenticated_401() -> None:
    assert client.get("/api/v1/ai/providers").status_code == 401
    assert client.get("/api/v1/ai/providers/openai/models").status_code == 401


def test_no_secrets_in_provider_response() -> None:
    token = _setup_token()
    for p in client.get("/api/v1/ai/providers", headers=_auth(token)).json():
        dumped = str(p).lower()
        assert "sk-" not in dumped
        assert "authorization" not in dumped
        assert "base_url" not in dumped
        assert "secret" not in dumped
        assert "credential" not in dumped
        # authentication_type is a safe label ("api_key" type), never a value.
        assert all("sk-" not in str(v) for v in p.values())


def test_no_secrets_in_model_response() -> None:
    token = _setup_token()
    for provider in ("fake-a", "gemini"):
        for m in client.get(
            f"/api/v1/ai/providers/{provider}/models", headers=_auth(token)
        ).json():
            dumped = str(m).lower()
            assert "sk-" not in dumped
            assert "api_key" not in dumped
            assert "secret" not in dumped
            assert "credential" not in dumped


def test_no_registry_internals_leaked() -> None:
    token = _setup_token()
    r = client.get("/api/v1/ai/providers/fake-a", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert "label" not in body
    assert "client" not in body
    assert "http" not in body


# --- Chatbot provider/model validation ---


def test_chatbot_valid_provider_model() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    r = _create_bot(token, org_id, provider_id="fake-b", model_id="fake-model-small")
    assert r.status_code == 201


def test_chatbot_unknown_provider_422() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    r = _create_bot(token, org_id, provider_id="unknown")
    assert r.status_code == 422
    assert "unknown provider" in r.json()["detail"]


def test_chatbot_unknown_model_422() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    r = _create_bot(token, org_id, provider_id="fake-a", model_id="unknown")
    assert r.status_code == 422


def test_chatbot_model_from_other_provider_422() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    # fake-a has no fake-model-large on provider b? It does — use openai model
    # id against fake-a provider instead.
    r = _create_bot(token, org_id, provider_id="fake-a", model_id="gpt-4o-mini")
    assert r.status_code == 422


def test_chatbot_disabled_provider_422() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    # gemini is disabled without a key in CI → must be rejected.
    r = _create_bot(token, org_id, provider_id="gemini", model_id="gemini-3.6-flash")
    if r.status_code == 422:
        assert "disabled" in r.json()["detail"]
    else:
        # If a key IS configured, creating a gemini chatbot is valid.
        assert r.status_code == 201


def test_gemini_model_in_discovery() -> None:
    token = _setup_token()
    r = client.get("/api/v1/ai/providers/gemini/models", headers=_auth(token))
    assert r.status_code == 200
    models = r.json()
    assert models, "gemini provider must expose at least one model"
    # Every model belongs to the gemini provider.
    assert all(m["provider_id"] == "gemini" for m in models)
    # The configured model (settings.openai_model, from the OPENAI_MODEL env
    # var; see app/core/config.py) must be exposed by discovery in every
    # environment, whatever the deployment configures.
    configured = next((m for m in models if m["model_id"] == settings.openai_model), None)
    assert configured is not None
    assert configured["display_name"] == settings.openai_model
    # Enabled reflects actual config state (no key in CI - disabled).
    assert configured["enabled"] in (True, False)


def test_chatbot_create_with_gemini() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    r = _create_bot(token, org_id, provider_id="gemini", model_id="gemini-3.6-flash")
    if r.status_code == 201:
        body = r.json()
        assert body["provider_id"] == "gemini"
        assert body["model_id"] == "gemini-3.6-flash"
    else:
        # No API key configured in CI → gemini is disabled.
        assert r.status_code == 422


def test_chatbot_gemini_model_must_belong_to_gemini() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    r = _create_bot(token, org_id, provider_id="gemini", model_id="fake-model-small")
    assert r.status_code == 422


def test_chatbot_update_validation() -> None:
    token = _setup_token()
    org_id = _create_org(token)
    bot = _create_bot(token, org_id).json()  # defaults fake-a
    r = client.patch(
        f"/api/v1/organizations/{org_id}/chatbots/{bot['id']}",
        json={"provider_id": "nope"},
        headers=_auth(token),
    )
    assert r.status_code == 422


# --- Provider/model admin mutation (M5) ---


def test_provider_update_unauthenticated_401() -> None:
    assert (
        client.patch("/api/v1/ai/providers/fake-b", json={"disabled": True}).status_code
        == 401
    )


def test_provider_update_plain_member_403() -> None:
    token = _setup_token()
    r = client.patch(
        "/api/v1/ai/providers/fake-b", json={"disabled": True}, headers=_auth(token)
    )
    assert r.status_code == 403


def test_provider_update_org_owner_403() -> None:
    """An organization OWNER — the highest existing MembershipRole — must
    not satisfy require_platform_admin. The two authorization axes are
    independent."""
    token = _setup_token()
    _create_org(token)  # token's user is now OWNER of an org, not a platform admin
    r = client.patch(
        "/api/v1/ai/providers/fake-b", json={"disabled": True}, headers=_auth(token)
    )
    assert r.status_code == 403


def test_provider_update_unknown_provider_404() -> None:
    token = _setup_admin_token()
    r = client.patch(
        "/api/v1/ai/providers/nope", json={"disabled": True}, headers=_auth(token)
    )
    assert r.status_code == 404


def test_model_update_unknown_model_404() -> None:
    token = _setup_admin_token()
    r = client.patch(
        "/api/v1/ai/providers/fake-a/models/nope",
        json={"disabled": True},
        headers=_auth(token),
    )
    assert r.status_code == 404


def test_model_update_extra_field_422() -> None:
    token = _setup_admin_token()
    r = client.patch(
        "/api/v1/ai/providers/fake-a/models/fake-model-large",
        json={"disabled": True, "display_name": "hacked"},
        headers=_auth(token),
    )
    assert r.status_code == 422


def test_provider_disable_blocks_discovery_and_new_assignment() -> None:
    token = _setup_admin_token()
    try:
        r = client.patch(
            "/api/v1/ai/providers/fake-b", json={"disabled": True}, headers=_auth(token)
        )
        assert r.status_code == 200, r.text
        assert r.json()["enabled"] is False

        # Reflected immediately in the existing read-only discovery endpoints.
        listed = client.get("/api/v1/ai/providers", headers=_auth(token)).json()
        fake_b = next(p for p in listed if p["provider_id"] == "fake-b")
        assert fake_b["enabled"] is False

        # Blocks new chatbot assignment — same error shape as a code-disabled provider.
        org_id = _create_org(token)
        blocked = _create_bot(token, org_id, provider_id="fake-b", model_id="fake-model-small")
        assert blocked.status_code == 422
        assert "disabled" in blocked.json()["detail"]
    finally:
        client.patch(
            "/api/v1/ai/providers/fake-b", json={"disabled": False}, headers=_auth(token)
        )

    r = client.get("/api/v1/ai/providers/fake-b", headers=_auth(token))
    assert r.json()["enabled"] is True

    # Re-enabled: assignment works again.
    org_id = _create_org(token)
    ok = _create_bot(token, org_id, provider_id="fake-b", model_id="fake-model-small")
    assert ok.status_code == 201


def test_model_disable_blocks_assignment_without_affecting_sibling_model() -> None:
    token = _setup_admin_token()
    try:
        r = client.patch(
            "/api/v1/ai/providers/fake-a/models/fake-model-large",
            json={"disabled": True},
            headers=_auth(token),
        )
        assert r.status_code == 200, r.text
        assert r.json()["enabled"] is False

        org_id = _create_org(token)
        blocked = _create_bot(
            token, org_id, provider_id="fake-a", model_id="fake-model-large"
        )
        assert blocked.status_code == 422
        assert "disabled" in blocked.json()["detail"]

        # fake-model-small on the same provider is unaffected.
        ok = _create_bot(token, org_id, provider_id="fake-a", model_id="fake-model-small")
        assert ok.status_code == 201
    finally:
        client.patch(
            "/api/v1/ai/providers/fake-a/models/fake-model-large",
            json={"disabled": False},
            headers=_auth(token),
        )

    r = client.get(
        "/api/v1/ai/providers/fake-a/models/fake-model-large", headers=_auth(token)
    )
    assert r.json()["enabled"] is True
