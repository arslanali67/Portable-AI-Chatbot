"""Platform-owner dashboard tests — the one deliberate cross-tenant read
surface in this codebase (architecture.md §8a). Covers list/detail field
correctness, the content-never-exposed boundary, platform-admin gating,
and the disable/enable toggle's enforcement across the admin-console
dependency functions and the public widget path.

Require Docker PostgreSQL + alembic upgrade head. Run: pytest -m identity
"""

import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import User
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.identity

client = TestClient(app)

PASSWORD = "strong-password-123"
_RUN = uuid.uuid4().hex[:8]

_FORBIDDEN_CONTENT_MARKERS = [
    "TOP_SECRET_SYSTEM_PROMPT_MARKER",
    "TOP_SECRET_USER_MESSAGE_MARKER",
]


def _email(name: str) -> str:
    return f"{name}-{_RUN}@example.com"


def _slug(name: str) -> str:
    return f"{name}-{_RUN}"


def _register(email: str, full_name: str = "Platform Tester"):
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
    return _login(_register(_email(f"user{uuid.uuid4().hex[:6]}"))["email"])


async def _promote_platform_admin(user_id: int) -> None:
    async with TestSessionLocal() as session:
        user = await session.get(User, user_id)
        user.is_platform_admin = True
        await session.commit()


def _setup_admin_token() -> str:
    email = _email(f"admin{uuid.uuid4().hex[:6]}")
    user = _register(email)
    asyncio.run(_promote_platform_admin(user["id"]))
    return _login(email)


def _create_org(token: str, name: str = "Org") -> int:
    r = client.post(
        "/api/v1/organizations",
        json={"name": name, "slug": _slug(f"org{uuid.uuid4().hex[:6]}")},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_bot(token: str, org_id: int, **overrides) -> int:
    payload = {"name": "Bot", "slug": _slug(f"bot{uuid.uuid4().hex[:6]}")}
    payload.update(overrides)
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots", json=payload, headers=_auth(token)
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_conv(token: str, org_id: int, bot_id: int) -> int:
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/conversations",
        json={"title": "Conv"},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _chat(token: str, org_id: int, conv_id: int, content: str):
    return client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv_id}/chat",
        json={"content": content},
        headers=_auth(token),
    )


def _setup_public_bot() -> tuple[str, int, int, str]:
    """Create org, active+public chatbot, widget config. Returns
    (owner_token, org_id, chatbot_id, public_key)."""
    token = _setup_token()
    org_id = _create_org(token)
    bot_id = _create_bot(token, org_id, welcome_message="Hi there")
    client.post(f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/activate", headers=_auth(token))
    r = client.patch(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}",
        json={"visibility": "public"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/widget-config", headers=_auth(token)
    )
    assert r.status_code == 201, r.text
    return token, org_id, bot_id, r.json()["public_key"]


def _session(public_key: str, origin: str = "https://example.com"):
    return client.post(
        "/api/v1/public/widget/session", json={"public_key": public_key, "origin": origin}
    )


def _stream(session_token: str, content: str, origin: str = "https://example.com"):
    return client.post(
        "/api/v1/public/widget/chat/stream",
        json={"session_token": session_token, "content": content, "origin": origin},
    )


def _parse_sse(response_text: str) -> list[tuple[str, dict]]:
    events = []
    for block in response_text.split("\n\n"):
        event = None
        data = None
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:"):].strip())
        if event and data is not None:
            events.append((event, data))
    return events


def _disable(admin_token: str, org_id: int, message: str | None = None):
    return client.post(
        f"/api/v1/platform/organizations/{org_id}/disable",
        json={"message": message},
        headers=_auth(admin_token),
    )


def _enable(admin_token: str, org_id: int):
    return client.post(
        f"/api/v1/platform/organizations/{org_id}/enable", headers=_auth(admin_token)
    )


# --- platform-admin gating: all 4 endpoints ---


def test_list_requires_auth_401() -> None:
    assert client.get("/api/v1/platform/organizations").status_code == 401


def test_list_plain_member_403() -> None:
    token = _setup_token()
    assert client.get("/api/v1/platform/organizations", headers=_auth(token)).status_code == 403


def test_list_org_owner_403() -> None:
    """An organization OWNER must not satisfy require_platform_admin —
    the two authorization axes are independent."""
    token = _setup_token()
    _create_org(token)
    assert client.get("/api/v1/platform/organizations", headers=_auth(token)).status_code == 403


def test_detail_plain_member_403() -> None:
    admin_token = _setup_admin_token()
    org_id = _create_org(admin_token)
    member_token = _setup_token()
    r = client.get(f"/api/v1/platform/organizations/{org_id}", headers=_auth(member_token))
    assert r.status_code == 403


def test_disable_plain_member_403() -> None:
    admin_token = _setup_admin_token()
    org_id = _create_org(admin_token)
    member_token = _setup_token()
    assert _disable(member_token, org_id).status_code == 403


def test_enable_plain_member_403() -> None:
    admin_token = _setup_admin_token()
    org_id = _create_org(admin_token)
    member_token = _setup_token()
    assert _enable(member_token, org_id).status_code == 403


# --- list/detail: fields, counts, content boundary ---


def test_list_returns_expected_fields_and_counts() -> None:
    admin_token = _setup_admin_token()
    owner_token = _setup_token()
    org_id = _create_org(owner_token, name="Field Test Org")
    _create_bot(owner_token, org_id)
    _create_bot(owner_token, org_id)

    r = client.get("/api/v1/platform/organizations", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and "total" in body and "limit" in body and "offset" in body

    # The list accumulates every organization ever created across this
    # shared test DB — ordered by id, our just-created org (highest id)
    # is guaranteed to land in the last page, not necessarily the first.
    total = body["total"]
    r = client.get(
        f"/api/v1/platform/organizations?limit=200&offset={max(0, total - 200)}",
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    match = next(item for item in r.json()["items"] if item["id"] == org_id)
    assert match["name"] == "Field Test Org"
    assert match["member_count"] == 1
    assert match["chatbot_count"] == 2
    assert match["owner_email"] is not None
    assert match["last_activity_at"] is None  # no conversations yet
    assert match["disabled_at"] is None


def test_detail_returns_members_chatbots_message_count() -> None:
    admin_token = _setup_admin_token()
    owner_token = _setup_token()
    org_id = _create_org(owner_token)
    bot_id = _create_bot(owner_token, org_id)
    conv_id = _create_conv(owner_token, org_id, bot_id)
    r = _chat(owner_token, org_id, conv_id, "hello")
    assert r.status_code == 200, r.text

    r = client.get(f"/api/v1/platform/organizations/{org_id}", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["members"]) == 1
    assert body["members"][0]["role"] == "owner"
    assert len(body["chatbots"]) == 1
    assert body["chatbots"][0]["status"] == "draft"
    # One user message + one assistant message persisted for this turn.
    assert body["message_count"] == 2
    assert body["last_activity_at"] is not None


def test_detail_unknown_org_404() -> None:
    admin_token = _setup_admin_token()
    assert client.get("/api/v1/platform/organizations/999999999", headers=_auth(admin_token)).status_code == 404


def test_list_and_detail_never_expose_message_or_system_prompt_content() -> None:
    """Explicit absence assertion, not just presence of the safe fields —
    a platform admin must never see another organization's message
    content or system_prompt anywhere in these responses."""
    admin_token = _setup_admin_token()
    owner_token = _setup_token()
    org_id = _create_org(owner_token)
    bot_id = _create_bot(
        owner_token, org_id, system_prompt="TOP_SECRET_SYSTEM_PROMPT_MARKER"
    )
    conv_id = _create_conv(owner_token, org_id, bot_id)
    r = _chat(owner_token, org_id, conv_id, "TOP_SECRET_USER_MESSAGE_MARKER")
    assert r.status_code == 200, r.text

    list_resp = client.get("/api/v1/platform/organizations", headers=_auth(admin_token))
    detail_resp = client.get(
        f"/api/v1/platform/organizations/{org_id}", headers=_auth(admin_token)
    )
    assert list_resp.status_code == 200 and detail_resp.status_code == 200

    for marker in _FORBIDDEN_CONTENT_MARKERS:
        assert marker not in list_resp.text
        assert marker not in detail_resp.text
    assert "system_prompt" not in detail_resp.text
    assert "credential" not in detail_resp.text.lower()
    assert "tool_execution_trace" not in detail_resp.text


# --- disable/enable: field mutation + admin-console enforcement ---


def test_disable_sets_fields_and_blocks_member_next_request() -> None:
    admin_token = _setup_admin_token()
    member_token = _setup_token()
    org_id = _create_org(member_token)  # member_token's user is OWNER of org_id

    # Confirm the member can access their own org before disabling.
    r = client.get(f"/api/v1/organizations/{org_id}", headers=_auth(member_token))
    assert r.status_code == 200, r.text

    r = _disable(admin_token, org_id, message="Payment overdue.")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["disabled_at"] is not None
    assert body["disabled_message"] == "Payment overdue."

    # The very next request from the existing, already-authenticated
    # session must be blocked — no new login, no token change.
    r = client.get(f"/api/v1/organizations/{org_id}", headers=_auth(member_token))
    assert r.status_code == 403
    assert "disabled" in r.json()["detail"].lower()

    # require_organization_role is a separate dependency function — must
    # also be blocked (chatbot creation route uses it).
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots",
        json={"name": "Bot", "slug": _slug("blockedbot")},
        headers=_auth(member_token),
    )
    assert r.status_code == 403


def test_disable_unknown_org_404() -> None:
    admin_token = _setup_admin_token()
    assert _disable(admin_token, 999999999).status_code == 404


def test_enable_clears_fields_and_restores_access() -> None:
    admin_token = _setup_admin_token()
    member_token = _setup_token()
    org_id = _create_org(member_token)

    assert _disable(admin_token, org_id, message="Temporary.").status_code == 200
    r = client.get(f"/api/v1/organizations/{org_id}", headers=_auth(member_token))
    assert r.status_code == 403

    r = _enable(admin_token, org_id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["disabled_at"] is None
    assert body["disabled_message"] is None

    # Same member, same session, next request succeeds again.
    r = client.get(f"/api/v1/organizations/{org_id}", headers=_auth(member_token))
    assert r.status_code == 200, r.text


def test_non_member_disabled_status_not_leaked() -> None:
    """A non-member must never learn a disabled org's status — gets the
    same 'Not a member' 403 whether the org is disabled or not."""
    admin_token = _setup_admin_token()
    owner_token = _setup_token()
    org_id = _create_org(owner_token)
    assert _disable(admin_token, org_id).status_code == 200

    outsider_token = _setup_token()
    r = client.get(f"/api/v1/organizations/{org_id}", headers=_auth(outsider_token))
    assert r.status_code == 403
    assert r.json()["detail"] == "Not a member of this organization"


# --- public widget: disabled organization ---


def test_public_widget_config_shows_configured_disabled_message() -> None:
    _owner_token, org_id, _bot_id, public_key = _setup_public_bot()
    admin_token = _setup_admin_token()
    assert _disable(admin_token, org_id, message="We are down for maintenance.").status_code == 200

    r = client.get("/api/v1/public/widget/config", params={"public_key": public_key})
    assert r.status_code == 403
    assert r.json()["detail"] == "We are down for maintenance."


def test_public_widget_config_generic_fallback_when_no_message() -> None:
    _owner_token, org_id, _bot_id, public_key = _setup_public_bot()
    admin_token = _setup_admin_token()
    assert _disable(admin_token, org_id).status_code == 200  # no message

    r = client.get("/api/v1/public/widget/config", params={"public_key": public_key})
    assert r.status_code == 403
    assert r.json()["detail"] == "This assistant is currently unavailable."


def test_public_widget_session_creation_blocked_when_disabled() -> None:
    _owner_token, org_id, _bot_id, public_key = _setup_public_bot()
    admin_token = _setup_admin_token()
    assert _disable(admin_token, org_id, message="Suspended.").status_code == 200

    r = _session(public_key)
    assert r.status_code == 403
    assert r.json()["detail"] == "Suspended."


def test_public_widget_stream_blocked_when_disabled_after_session_created() -> None:
    """A session created before disabling must not let chat/stream
    proceed afterward — the check runs on every request, not just at
    session-creation time."""
    _owner_token, org_id, _bot_id, public_key = _setup_public_bot()
    session_token = _session(public_key).json()["session_token"]

    admin_token = _setup_admin_token()
    assert _disable(admin_token, org_id, message="Closed.").status_code == 200

    r = _stream(session_token, "hello")
    assert r.status_code == 200  # SSE endpoint always 200s; error rides in the stream
    events = _parse_sse(r.text)
    assert events[0] == ("error", {"detail": "Closed."})
    assert not any(etype == "token" for etype, _ in events)
    assert not any(etype == "end" for etype, _ in events)


def test_public_widget_restored_after_enable() -> None:
    _owner_token, org_id, _bot_id, public_key = _setup_public_bot()
    admin_token = _setup_admin_token()
    assert _disable(admin_token, org_id).status_code == 200
    assert client.get("/api/v1/public/widget/config", params={"public_key": public_key}).status_code == 403

    assert _enable(admin_token, org_id).status_code == 200
    r = client.get("/api/v1/public/widget/config", params={"public_key": public_key})
    assert r.status_code == 200, r.text
