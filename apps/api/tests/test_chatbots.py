"""Chatbot CRUD tests — tenant isolation, roles, validation, lifecycle.

Require Docker PostgreSQL + alembic upgrade head. Run: pytest -m identity
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.identity

client = TestClient(app)

PASSWORD = "strong-password-123"
_RUN = uuid.uuid4().hex[:8]


def _email(name: str) -> str:
    return f"{name}-{_RUN}@example.com"


def _slug(name: str) -> str:
    return f"{name}-{_RUN}"


def _register(email: str, full_name: str = "Bot Tester"):
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
        "/api/v1/organizations",
        json={"name": name, "slug": slug},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _bot_payload(slug: str | None = None, **overrides) -> dict:
    payload = {
        "name": "Support Bot",
        "slug": slug or _slug("support-bot"),
        "description": "Support assistant",
        "system_prompt": "You are a support assistant.",
        "welcome_message": "Hello!",
        "language": "en",
        "visibility": "private",
    }
    payload.update(overrides)
    return payload


def _create_bot(token: str, org_id: int, **overrides):
    return client.post(
        f"/api/v1/organizations/{org_id}/chatbots",
        json=_bot_payload(**overrides),
        headers=_auth(token),
    )


async def _set_role(user_email: str, org_id: int, role: str) -> None:
    async with TestSessionLocal() as s:
        # Ensure a membership row exists, then set role.
        await s.execute(
            text(
                "INSERT INTO memberships (user_id, organization_id, role) "
                "SELECT id, :oid, :role FROM users WHERE email = :email "
                "ON CONFLICT (user_id, organization_id) DO UPDATE SET role = EXCLUDED.role"
            ),
            {"role": role, "oid": org_id, "email": user_email},
        )
        await s.commit()


# --- Fixture helpers ---


def _setup_owner() -> tuple[str, str, int]:
    email = _email(f"owner{uuid.uuid4().hex[:6]}")
    token = _login(_register(email)["email"])
    org_id = _create_org(token, "Owner Org", _slug(f"owner-org{uuid.uuid4().hex[:6]}"))
    return email, token, org_id


def _setup_member(org_id: int) -> str:
    email = _email(f"member{uuid.uuid4().hex[:6]}")
    _register(email)
    token = _login(email)
    import asyncio

    asyncio.run(_set_role(email, org_id, "member"))
    return token


# --- Tenant isolation ---


def test_org_a_cannot_see_org_b_chatbots() -> None:
    email_a, token_a, org_a = _setup_owner()
    email_b, token_b, org_b = _setup_owner()
    _create_bot(token_a, org_a)
    _create_bot(token_b, org_b)

    bots_a = client.get(f"/api/v1/organizations/{org_a}/chatbots", headers=_auth(token_a))
    bots_b = client.get(f"/api/v1/organizations/{org_b}/chatbots", headers=_auth(token_b))
    assert bots_a.status_code == 200
    assert bots_b.status_code == 200
    assert len(bots_a.json()) == 1
    assert len(bots_b.json()) == 1

    # A cannot list B's bots through B's org (no membership).
    cross = client.get(f"/api/v1/organizations/{org_b}/chatbots", headers=_auth(token_a))
    assert cross.status_code == 403


def test_cannot_get_other_org_bot() -> None:
    email_a, token_a, org_a = _setup_owner()
    email_b, token_b, org_b = _setup_owner()
    bot_id = _create_bot(token_a, org_a).json()["id"]

    # B with bot id from A: not member of A org -> 403, or 404 if org id wrong.
    r = client.get(
        f"/api/v1/organizations/{org_a}/chatbots/{bot_id}", headers=_auth(token_b)
    )
    assert r.status_code == 403


def test_cannot_update_other_org_bot() -> None:
    email_a, token_a, org_a = _setup_owner()
    email_b, token_b, org_b = _setup_owner()
    bot_id = _create_bot(token_a, org_a).json()["id"]
    r = client.patch(
        f"/api/v1/organizations/{org_a}/chatbots/{bot_id}",
        json={"name": "Hacked"},
        headers=_auth(token_b),
    )
    assert r.status_code == 403


def test_cannot_archive_other_org_bot() -> None:
    email_a, token_a, org_a = _setup_owner()
    email_b, token_b, org_b = _setup_owner()
    bot_id = _create_bot(token_a, org_a).json()["id"]
    r = client.post(
        f"/api/v1/organizations/{org_a}/chatbots/{bot_id}/archive", headers=_auth(token_b)
    )
    assert r.status_code == 403


def test_cannot_delete_other_org_bot() -> None:
    email_a, token_a, org_a = _setup_owner()
    email_b, token_b, org_b = _setup_owner()
    bot_id = _create_bot(token_a, org_a).json()["id"]
    r = client.delete(
        f"/api/v1/organizations/{org_a}/chatbots/{bot_id}", headers=_auth(token_b)
    )
    assert r.status_code == 403


def test_guessing_org_id_does_not_bypass_membership() -> None:
    email_a, token_a, org_a = _setup_owner()
    email_b, token_b, _ = _setup_owner()
    # B guesses random org ids — no membership anywhere.
    for guess in (999_999, 999_998):
        r = client.get(f"/api/v1/organizations/{guess}/chatbots", headers=_auth(token_b))
        assert r.status_code == 404


# --- Roles ---


def test_owner_full_crud() -> None:
    email, token, org_id = _setup_owner()
    bot = _create_bot(token, org_id)
    assert bot.status_code == 201
    bot_id = bot.json()["id"]
    assert client.get(f"/api/v1/organizations/{org_id}/chatbots/{bot_id}", headers=_auth(token)).status_code == 200
    assert client.patch(f"/api/v1/organizations/{org_id}/chatbots/{bot_id}", json={"name": "New"}, headers=_auth(token)).status_code == 200
    assert client.post(f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/activate", headers=_auth(token)).status_code == 200
    assert client.post(f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/archive", headers=_auth(token)).status_code == 200
    assert client.delete(f"/api/v1/organizations/{org_id}/chatbots/{bot_id}", headers=_auth(token)).status_code == 204


def test_admin_full_crud() -> None:
    email, token, org_id = _setup_owner()
    import asyncio

    asyncio.run(_set_role(email, org_id, "admin"))
    bot = _create_bot(token, org_id)
    assert bot.status_code == 201
    bot_id = bot.json()["id"]
    assert client.patch(f"/api/v1/organizations/{org_id}/chatbots/{bot_id}", json={"name": "Admin"}, headers=_auth(token)).status_code == 200
    assert client.post(f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/activate", headers=_auth(token)).status_code == 200
    assert client.post(f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/archive", headers=_auth(token)).status_code == 200
    assert client.delete(f"/api/v1/organizations/{org_id}/chatbots/{bot_id}", headers=_auth(token)).status_code == 204


def test_member_read_only() -> None:
    email, owner_token, org_id = _setup_owner()
    bot_id = _create_bot(owner_token, org_id).json()["id"]
    member_token = _setup_member(org_id)

    # Read allowed.
    assert client.get(f"/api/v1/organizations/{org_id}/chatbots", headers=_auth(member_token)).status_code == 200
    assert client.get(f"/api/v1/organizations/{org_id}/chatbots/{bot_id}", headers=_auth(member_token)).status_code == 200

    # Writes forbidden.
    assert client.post(f"/api/v1/organizations/{org_id}/chatbots", json=_bot_payload(_slug("member-bot")), headers=_auth(member_token)).status_code == 403
    assert client.patch(f"/api/v1/organizations/{org_id}/chatbots/{bot_id}", json={"name": "X"}, headers=_auth(member_token)).status_code == 403
    assert client.post(f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/activate", headers=_auth(member_token)).status_code == 403
    assert client.post(f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/archive", headers=_auth(member_token)).status_code == 403
    assert client.delete(f"/api/v1/organizations/{org_id}/chatbots/{bot_id}", headers=_auth(member_token)).status_code == 403


# --- Validation ---


def test_missing_name_422() -> None:
    _, token, org_id = _setup_owner()
    payload = _bot_payload()
    del payload["name"]
    assert client.post(f"/api/v1/organizations/{org_id}/chatbots", json=payload, headers=_auth(token)).status_code == 422


def test_empty_name_422() -> None:
    _, token, org_id = _setup_owner()
    assert _create_bot(token, org_id, name="").status_code == 422


def test_invalid_slug_422() -> None:
    _, token, org_id = _setup_owner()
    assert _create_bot(token, org_id, slug="Bad Slug!").status_code == 422


def test_duplicate_slug_same_org_409() -> None:
    _, token, org_id = _setup_owner()
    slug = _slug("dup-bot")
    assert _create_bot(token, org_id, slug=slug).status_code == 201
    assert _create_bot(token, org_id, slug=slug).status_code == 409


def test_same_slug_different_orgs_allowed() -> None:
    _, token_a, org_a = _setup_owner()
    _, token_b, org_b = _setup_owner()
    slug = _slug("shared")
    assert _create_bot(token_a, org_a, slug=slug).status_code == 201
    assert _create_bot(token_b, org_b, slug=slug).status_code == 201


def test_invalid_visibility_422() -> None:
    _, token, org_id = _setup_owner()
    assert _create_bot(token, org_id, visibility="secret").status_code == 422


def test_invalid_status_on_create_rejected() -> None:
    """Status is not freely choosable — extra field rejected or ignored."""
    _, token, org_id = _setup_owner()
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots",
        json=_bot_payload(status="active"),
        headers=_auth(token),
    )
    # Either 422 (extra forbidden) or status forced to draft. Ours: extra field
    # rejected by default model config -> 422.
    assert r.status_code == 422


def test_invalid_language_422() -> None:
    _, token, org_id = _setup_owner()
    assert _create_bot(token, org_id, language="xx").status_code == 422


def test_overly_long_field_422() -> None:
    _, token, org_id = _setup_owner()
    assert _create_bot(token, org_id, name="x" * 256).status_code == 422


def test_partial_patch() -> None:
    _, token, org_id = _setup_owner()
    bot = _create_bot(token, org_id).json()
    r = client.patch(
        f"/api/v1/organizations/{org_id}/chatbots/{bot['id']}",
        json={"welcome_message": "Updated welcome"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["welcome_message"] == "Updated welcome"
    assert body["name"] == bot["name"]
    assert body["slug"] == bot["slug"]


def test_patch_cannot_change_organization_id() -> None:
    _, token, org_id = _setup_owner()
    bot = _create_bot(token, org_id).json()
    r = client.patch(
        f"/api/v1/organizations/{org_id}/chatbots/{bot['id']}",
        json={"organization_id": 999},
        headers=_auth(token),
    )
    # Unknown field rejected by schema -> 422; immutable field never applied.
    assert r.status_code == 422


# --- Lifecycle ---


def test_lifecycle_transitions() -> None:
    _, token, org_id = _setup_owner()
    bot = _create_bot(token, org_id).json()
    assert bot["status"] == "draft"

    r = client.post(f"/api/v1/organizations/{org_id}/chatbots/{bot['id']}/activate", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["status"] == "active"

    r = client.post(f"/api/v1/organizations/{org_id}/chatbots/{bot['id']}/archive", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["status"] == "archived"

    # archived -> active forbidden
    r = client.post(f"/api/v1/organizations/{org_id}/chatbots/{bot['id']}/activate", headers=_auth(token))
    assert r.status_code == 409


def test_draft_to_archived_allowed() -> None:
    _, token, org_id = _setup_owner()
    bot = _create_bot(token, org_id).json()
    r = client.post(f"/api/v1/organizations/{org_id}/chatbots/{bot['id']}/archive", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["status"] == "archived"


def test_active_to_archived_allowed() -> None:
    _, token, org_id = _setup_owner()
    bot = _create_bot(token, org_id).json()
    client.post(f"/api/v1/organizations/{org_id}/chatbots/{bot['id']}/activate", headers=_auth(token))
    r = client.post(f"/api/v1/organizations/{org_id}/chatbots/{bot['id']}/archive", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["status"] == "archived"


# --- AI configuration ---


def test_provider_model_saved_on_create() -> None:
    _, token, org_id = _setup_owner()
    r = _create_bot(token, org_id, provider_id="fake-b", model_id="fake-model-small")
    assert r.status_code == 201
    body = r.json()
    assert body["provider_id"] == "fake-b"
    assert body["model_id"] == "fake-model-small"


def test_provider_model_defaults() -> None:
    _, token, org_id = _setup_owner()
    bot = _create_bot(token, org_id).json()
    assert bot["provider_id"] == "fake-a"
    assert bot["model_id"] == "fake-model-small"


def test_provider_model_patch() -> None:
    _, token, org_id = _setup_owner()
    bot = _create_bot(token, org_id).json()
    r = client.patch(
        f"/api/v1/organizations/{org_id}/chatbots/{bot['id']}",
        json={"provider_id": "fake-b", "model_id": "fake-model-small"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["provider_id"] == "fake-b"
    assert body["model_id"] == "fake-model-small"


def test_invalid_provider_id_422() -> None:
    _, token, org_id = _setup_owner()
    assert _create_bot(token, org_id, provider_id="bad id!").status_code == 422


def test_invalid_model_id_422() -> None:
    _, token, org_id = _setup_owner()
    assert _create_bot(token, org_id, model_id="bad model!").status_code == 422


def test_rag_config_defaults() -> None:
    _, token, org_id = _setup_owner()
    bot = _create_bot(token, org_id).json()
    assert bot["rag_enabled"] is True
    assert bot["rag_top_k"] is None


def test_rag_config_saved_on_create() -> None:
    _, token, org_id = _setup_owner()
    r = _create_bot(token, org_id, rag_enabled=False, rag_top_k=3)
    assert r.status_code == 201
    body = r.json()
    assert body["rag_enabled"] is False
    assert body["rag_top_k"] == 3


def test_rag_config_patch() -> None:
    _, token, org_id = _setup_owner()
    bot = _create_bot(token, org_id).json()
    r = client.patch(
        f"/api/v1/organizations/{org_id}/chatbots/{bot['id']}",
        json={"rag_enabled": False, "rag_top_k": 10},
        headers=_auth(token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["rag_enabled"] is False
    assert body["rag_top_k"] == 10


def test_rag_top_k_patch_can_be_cleared_back_to_default() -> None:
    """Explicit null in the PATCH body clears rag_top_k back to NULL (use
    the global default) — distinct from omitting the field entirely."""
    _, token, org_id = _setup_owner()
    bot = _create_bot(token, org_id, rag_top_k=8).json()
    r = client.patch(
        f"/api/v1/organizations/{org_id}/chatbots/{bot['id']}",
        json={"rag_top_k": None},
        headers=_auth(token),
    )
    assert r.status_code == 200
    assert r.json()["rag_top_k"] is None


def test_invalid_rag_top_k_too_low_422() -> None:
    _, token, org_id = _setup_owner()
    assert _create_bot(token, org_id, rag_top_k=0).status_code == 422


def test_invalid_rag_top_k_too_high_422() -> None:
    _, token, org_id = _setup_owner()
    assert _create_bot(token, org_id, rag_top_k=21).status_code == 422
