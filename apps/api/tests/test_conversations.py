"""Conversation + message tests — ownership, lifecycle, roles, tenant
isolation, pagination, immutability.

Require Docker PostgreSQL + alembic upgrade head. Run: pytest -m identity
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.identity

client = TestClient(app)

PASSWORD = "Strong-password-123"
_RUN = uuid.uuid4().hex[:8]


def _email(name: str) -> str:
    return f"{name}-{_RUN}@example.com"


def _slug(name: str) -> str:
    return f"{name}-{_RUN}"


def _register(email: str, full_name: str = "Conv Tester"):
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


def _create_bot(token: str, org_id: int, slug: str) -> int:
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots",
        json={"name": "Bot", "slug": slug},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _setup_owner() -> tuple[str, str, int, int]:
    email = _email(f"owner{uuid.uuid4().hex[:6]}")
    token = _login(_register(email)["email"])
    org_id = _create_org(token, "Org", _slug(f"org{uuid.uuid4().hex[:6]}"))
    bot_id = _create_bot(token, org_id, _slug(f"bot{uuid.uuid4().hex[:6]}"))
    return email, token, org_id, bot_id


def _setup_member(org_id: int, role: str = "member") -> str:
    email = _email(f"user{uuid.uuid4().hex[:6]}")
    _register(email)
    token = _login(email)
    import asyncio

    asyncio.run(_set_role(email, org_id, role))
    return token


async def _set_role(user_email: str, org_id: int, role: str) -> None:
    from sqlalchemy import text

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


def _create_conv(token: str, org_id: int, bot_id: int, title: str = "Conv") -> dict:
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/conversations",
        json={"title": title},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()


def _post_message(token: str, org_id: int, conv_id: int, content: str = "hello", **overrides):
    payload = {"content": content}
    payload.update(overrides)
    return client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv_id}/messages",
        json=payload,
        headers=_auth(token),
    )


# --- Conversations ---


def test_create_conversation() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    assert conv["status"] == "active"
    assert conv["chatbot_id"] == bot_id
    assert conv["organization_id"] == org_id
    assert conv["user_id"] > 0
    assert conv["title"] == "Conv"


def test_list_conversations() -> None:
    _, token, org_id, bot_id = _setup_owner()
    _create_conv(token, org_id, bot_id)
    _create_conv(token, org_id, bot_id, title="Second")
    r = client.get(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/conversations",
        headers=_auth(token),
    )
    assert r.status_code == 200
    assert r.json()["total"] == 2
    assert len(r.json()["items"]) == 2


def test_get_conversation() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    r = client.get(
        f"/api/v1/organizations/{org_id}/conversations/{conv['id']}", headers=_auth(token)
    )
    assert r.status_code == 200
    assert r.json()["id"] == conv["id"]


def test_archive_conversation() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    r = client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv['id']}/archive",
        headers=_auth(token),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "archived"


def _rename(token: str, org_id: int, conv_id: int, title):
    return client.patch(
        f"/api/v1/organizations/{org_id}/conversations/{conv_id}",
        json={"title": title},
        headers=_auth(token),
    )


def test_rename_conversation() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    r = _rename(token, org_id, conv["id"], "Renamed")
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Renamed"


def test_rename_empty_title_422() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    assert _rename(token, org_id, conv["id"], "").status_code == 422


def test_rename_too_long_title_422() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    assert _rename(token, org_id, conv["id"], "x" * 256).status_code == 422


def test_rename_max_length_boundary_accepted() -> None:
    """255 chars is the same bound ConversationCreate.title already accepts."""
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    r = _rename(token, org_id, conv["id"], "x" * 255)
    assert r.status_code == 200, r.text


def test_member_cannot_rename_another_member_conversation() -> None:
    _, owner_token, org_id, bot_id = _setup_owner()
    member1 = _setup_member(org_id, "member")
    member2 = _setup_member(org_id, "member")
    conv = _create_conv(member1, org_id, bot_id)
    r = _rename(member2, org_id, conv["id"], "Hijacked")
    assert r.status_code == 403


def test_owner_can_rename_members_conversation() -> None:
    _, owner_token, org_id, bot_id = _setup_owner()
    member_token = _setup_member(org_id, "member")
    conv = _create_conv(member_token, org_id, bot_id)
    r = _rename(owner_token, org_id, conv["id"], "Renamed by owner")
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Renamed by owner"


def test_cannot_rename_archived_conversation() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    r = client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv['id']}/archive",
        headers=_auth(token),
    )
    assert r.status_code == 200
    r2 = _rename(token, org_id, conv["id"], "Too late")
    assert r2.status_code == 409, r2.text


def test_cannot_create_conversation_for_other_org_chatbot() -> None:
    _, token_a, org_a, bot_a = _setup_owner()
    _, token_b, org_b, bot_b = _setup_owner()
    # A tries to create conversation on B's chatbot via B's org path.
    r = client.post(
        f"/api/v1/organizations/{org_b}/chatbots/{bot_b}/conversations",
        json={"title": "Hack"},
        headers=_auth(token_a),
    )
    assert r.status_code == 403
    # A tries B's chatbot id through A's org path.
    r2 = client.post(
        f"/api/v1/organizations/{org_a}/chatbots/{bot_b}/conversations",
        json={"title": "Hack"},
        headers=_auth(token_a),
    )
    assert r2.status_code == 404


def test_cannot_access_other_org_conversation() -> None:
    _, token_a, org_a, bot_a = _setup_owner()
    _, token_b, org_b, bot_b = _setup_owner()
    conv = _create_conv(token_a, org_a, bot_a)
    r = client.get(
        f"/api/v1/organizations/{org_a}/conversations/{conv['id']}", headers=_auth(token_b)
    )
    assert r.status_code == 403


def test_cannot_archive_other_org_conversation() -> None:
    _, token_a, org_a, bot_a = _setup_owner()
    _, token_b, org_b, bot_b = _setup_owner()
    conv = _create_conv(token_a, org_a, bot_a)
    r = client.post(
        f"/api/v1/organizations/{org_a}/conversations/{conv['id']}/archive",
        headers=_auth(token_b),
    )
    assert r.status_code == 403


def test_id_guessing_does_not_bypass_membership() -> None:
    _, token_a, org_a, bot_a = _setup_owner()
    _, token_b, org_b, bot_b = _setup_owner()
    _create_conv(token_b, org_b, bot_b)
    for guess in (999_999, 999_998):
        r = client.get(
            f"/api/v1/organizations/{org_a}/conversations/{guess}", headers=_auth(token_a)
        )
        assert r.status_code == 404


# --- Messages ---


def test_create_user_message() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    r = _post_message(token, org_id, conv["id"])
    assert r.status_code == 201
    body = r.json()
    assert body["role"] == "user"
    assert body["content"] == "hello"
    assert body["sequence_number"] == 1
    assert body["conversation_id"] == conv["id"]


def test_sequence_increments() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    m1 = _post_message(token, org_id, conv["id"], "first").json()
    m2 = _post_message(token, org_id, conv["id"], "second").json()
    assert m1["sequence_number"] == 1
    assert m2["sequence_number"] == 2


def test_sequence_ordering() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    _post_message(token, org_id, conv["id"], "one")
    _post_message(token, org_id, conv["id"], "two")
    r = client.get(
        f"/api/v1/organizations/{org_id}/conversations/{conv['id']}/messages",
        headers=_auth(token),
    )
    seqs = [m["sequence_number"] for m in r.json()["items"]]
    assert seqs == [1, 2]


def test_assistant_role_rejected() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    r = _post_message(token, org_id, conv["id"], role="assistant")
    assert r.status_code == 422


def test_system_role_rejected() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    r = _post_message(token, org_id, conv["id"], role="system")
    assert r.status_code == 422


def test_sequence_number_client_rejected() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    r = _post_message(token, org_id, conv["id"], sequence_number=99)
    assert r.status_code == 422


def test_conversation_id_client_rejected() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    r = _post_message(token, org_id, conv["id"], conversation_id=123)
    assert r.status_code == 422


def test_message_immutable_no_patch_delete() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    msg = _post_message(token, org_id, conv["id"]).json()
    # No PATCH/DELETE routes exist for messages — endpoint does not exist.
    r = client.patch(
        f"/api/v1/organizations/{org_id}/conversations/{conv['id']}/messages/{msg['id']}",
        json={"content": "changed"},
        headers=_auth(token),
    )
    assert r.status_code in (404, 405)
    r2 = client.delete(
        f"/api/v1/organizations/{org_id}/conversations/{conv['id']}/messages/{msg['id']}",
        headers=_auth(token),
    )
    assert r2.status_code in (404, 405)


def test_cross_org_message_access_denied() -> None:
    _, token_a, org_a, bot_a = _setup_owner()
    _, token_b, org_b, bot_b = _setup_owner()
    conv = _create_conv(token_a, org_a, bot_a)
    _post_message(token_a, org_a, conv["id"])
    r = client.get(
        f"/api/v1/organizations/{org_a}/conversations/{conv['id']}/messages",
        headers=_auth(token_b),
    )
    assert r.status_code == 403
    r2 = _post_message(token_b, org_a, conv["id"])
    assert r2.status_code == 403


def test_archived_conversation_rejects_message() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv['id']}/archive",
        headers=_auth(token),
    )
    r = _post_message(token, org_id, conv["id"])
    assert r.status_code == 409
    # Still readable.
    r2 = client.get(
        f"/api/v1/organizations/{org_id}/conversations/{conv['id']}",
        headers=_auth(token),
    )
    assert r2.status_code == 200


def test_metadata_works() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    r = _post_message(token, org_id, conv["id"], metadata={"source": "web"})
    assert r.status_code == 201
    assert r.json()["metadata"] == {"source": "web"}


def test_pagination() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    for i in range(5):
        _post_message(token, org_id, conv["id"], f"msg-{i}")
    r = client.get(
        f"/api/v1/organizations/{org_id}/conversations/{conv['id']}/messages",
        params={"limit": 2, "offset": 0},
        headers=_auth(token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert [m["sequence_number"] for m in body["items"]] == [1, 2]
    r2 = client.get(
        f"/api/v1/organizations/{org_id}/conversations/{conv['id']}/messages",
        params={"limit": 2, "offset": 2},
        headers=_auth(token),
    )
    assert [m["sequence_number"] for m in r2.json()["items"]] == [3, 4]


def test_list_sorts_by_last_activity_not_creation_order() -> None:
    """Proves updated_at-on-message actually changes ordering, not just
    that the column exists: A is created first (older by id/created_at),
    then a message lands on A after B is created, so A must sort first."""
    _, token, org_id, bot_id = _setup_owner()
    conv_a = _create_conv(token, org_id, bot_id, title="A")
    conv_b = _create_conv(token, org_id, bot_id, title="B")

    r = client.get(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/conversations",
        headers=_auth(token),
    )
    titles_before = [c["title"] for c in r.json()["items"]]
    assert titles_before == ["B", "A"], "sanity: newest-created listed first"

    assert _post_message(token, org_id, conv_a["id"], "wake A up").status_code == 201

    r2 = client.get(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/conversations",
        headers=_auth(token),
    )
    titles_after = [c["title"] for c in r2.json()["items"]]
    assert titles_after == ["A", "B"], (
        "A received a message after B was created, so A must now sort first "
        "by last activity — proves updated_at is actually touched, not just present"
    )


# --- Roles ---


def test_owner_full_permissions() -> None:
    _, token, org_id, bot_id = _setup_owner()
    conv = _create_conv(token, org_id, bot_id)
    assert _post_message(token, org_id, conv["id"]).status_code == 201
    assert client.get(
        f"/api/v1/organizations/{org_id}/conversations/{conv['id']}/messages",
        headers=_auth(token),
    ).status_code == 200
    assert client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv['id']}/archive",
        headers=_auth(token),
    ).status_code == 200


def test_admin_archives_any_conversation() -> None:
    _, owner_token, org_id, bot_id = _setup_owner()
    conv = _create_conv(owner_token, org_id, bot_id)
    admin_token = _setup_member(org_id, "admin")
    r = client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv['id']}/archive",
        headers=_auth(admin_token),
    )
    assert r.status_code == 200


def test_member_creates_and_reads_own() -> None:
    _, owner_token, org_id, bot_id = _setup_owner()
    member_token = _setup_member(org_id, "member")
    conv = _create_conv(member_token, org_id, bot_id)
    assert _post_message(member_token, org_id, conv["id"]).status_code == 201
    assert client.get(
        f"/api/v1/organizations/{org_id}/conversations/{conv['id']}",
        headers=_auth(member_token),
    ).status_code == 200


def test_member_cannot_access_another_member_conversation() -> None:
    _, owner_token, org_id, bot_id = _setup_owner()
    member1 = _setup_member(org_id, "member")
    member2 = _setup_member(org_id, "member")
    conv = _create_conv(member1, org_id, bot_id)
    r = client.get(
        f"/api/v1/organizations/{org_id}/conversations/{conv['id']}",
        headers=_auth(member2),
    )
    assert r.status_code == 403
    r2 = _post_message(member2, org_id, conv["id"])
    assert r2.status_code == 403
    r3 = client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv['id']}/archive",
        headers=_auth(member2),
    )
    assert r3.status_code == 403


def test_member_list_shows_own_only() -> None:
    _, owner_token, org_id, bot_id = _setup_owner()
    member1 = _setup_member(org_id, "member")
    member2 = _setup_member(org_id, "member")
    _create_conv(member1, org_id, bot_id, title="M1")
    _create_conv(member2, org_id, bot_id, title="M2")
    r = client.get(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/conversations",
        headers=_auth(member1),
    )
    titles = [c["title"] for c in r.json()["items"]]
    assert titles == ["M1"]


def test_owner_sees_all_conversations() -> None:
    _, owner_token, org_id, bot_id = _setup_owner()
    member1 = _setup_member(org_id, "member")
    _create_conv(member1, org_id, bot_id, title="MemberConv")
    r = client.get(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/conversations",
        headers=_auth(owner_token),
    )
    titles = [c["title"] for c in r.json()["items"]]
    assert "MemberConv" in titles
