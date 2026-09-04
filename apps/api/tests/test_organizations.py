"""Organization management tests — detail/rename/delete, membership CRUD,
owner/admin/member role semantics, last-owner protection, and tenant
isolation (Milestone M3).

Require the project's Docker PostgreSQL (docker compose up -d postgres), a
valid .env, and identity tables (alembic upgrade head). Run with:
pytest -m identity
"""

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.identity

client = TestClient(app)

PASSWORD = "Strong-password-123"
_RUN = uuid.uuid4().hex[:8]


def _email(name: str) -> str:
    return f"{name}-{_RUN}-{uuid.uuid4().hex[:6]}@example.com"


def _slug(name: str) -> str:
    return f"{name}-{_RUN}-{uuid.uuid4().hex[:6]}"


def _register(email: str, full_name: str = "Org Tester") -> dict:
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


async def _membership_id_query(org_id: int, email: str) -> int:
    async with TestSessionLocal() as s:
        result = await s.execute(
            text(
                "SELECT m.id FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE m.organization_id = :oid AND u.email = :email"
            ),
            {"oid": org_id, "email": email},
        )
        return result.scalar_one()


def _mid(org_id: int, email: str) -> int:
    return asyncio.run(_membership_id_query(org_id, email))


def _setup_owner(label: str) -> tuple[str, str, int]:
    email = _email(f"owner-{label}")
    _register(email)
    token = _login(email)
    org_id = _create_org(token, f"Org {label}", _slug(f"org-{label}"))
    return email, token, org_id


def _add_user_with_role(org_id: int, role: str, label: str) -> tuple[str, str]:
    """Register a second user and place them directly into org_id at role,
    bypassing the add-member endpoint (which is exercised separately)."""
    email = _email(label)
    _register(email)
    token = _login(email)
    asyncio.run(_set_role(email, org_id, role))
    return email, token


# --- API wrappers ---


def _get_org(token: str, org_id: int):
    return client.get(f"/api/v1/organizations/{org_id}", headers=_auth(token))


def _patch_org(token: str, org_id: int, name: str):
    return client.patch(
        f"/api/v1/organizations/{org_id}", json={"name": name}, headers=_auth(token)
    )


def _delete_org(token: str, org_id: int):
    return client.delete(f"/api/v1/organizations/{org_id}", headers=_auth(token))


def _list_members(token: str, org_id: int):
    return client.get(f"/api/v1/organizations/{org_id}/members", headers=_auth(token))


def _add_member(token: str, org_id: int, email: str, role: str = "member"):
    return client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": email, "role": role},
        headers=_auth(token),
    )


def _patch_member(token: str, org_id: int, membership_id: int, role: str):
    return client.patch(
        f"/api/v1/organizations/{org_id}/members/{membership_id}",
        json={"role": role},
        headers=_auth(token),
    )


def _delete_member(token: str, org_id: int, membership_id: int):
    return client.delete(
        f"/api/v1/organizations/{org_id}/members/{membership_id}", headers=_auth(token)
    )


# --- 1. Organization detail ---


def test_member_can_read_organization_detail() -> None:
    _, token, org_id = _setup_owner("detail")
    r = _get_org(token, org_id)
    assert r.status_code == 200
    assert r.json()["id"] == org_id


def test_non_member_cannot_read_organization_detail() -> None:
    _, _, org_a = _setup_owner("detail-a")
    _, token_b, _ = _setup_owner("detail-b")
    assert _get_org(token_b, org_a).status_code == 403


def test_nonexistent_organization_detail_returns_404() -> None:
    _, token, _ = _setup_owner("detail-404")
    assert _get_org(token, 999_999_999).status_code == 404


# --- 2. Rename ---


def test_owner_can_rename_organization() -> None:
    _, token, org_id = _setup_owner("rename-owner")
    r = _patch_org(token, org_id, "Renamed By Owner")
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed By Owner"


def test_admin_can_rename_organization() -> None:
    _, _, org_id = _setup_owner("rename-admin-owner")
    _, admin_token = _add_user_with_role(org_id, "admin", "rename-admin")
    r = _patch_org(admin_token, org_id, "Renamed By Admin")
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed By Admin"


def test_member_cannot_rename_organization() -> None:
    _, _, org_id = _setup_owner("rename-member-owner")
    _, member_token = _add_user_with_role(org_id, "member", "rename-member")
    assert _patch_org(member_token, org_id, "Hacked Name").status_code == 403


def test_rename_keeps_slug_unchanged() -> None:
    _, token, org_id = _setup_owner("rename-slug")
    before_slug = _get_org(token, org_id).json()["slug"]
    r = _patch_org(token, org_id, "New Display Name")
    assert r.status_code == 200
    assert r.json()["slug"] == before_slug


# --- 3. Delete ---


def test_owner_can_delete_organization() -> None:
    _, token, org_id = _setup_owner("delete-owner")
    assert _delete_org(token, org_id).status_code == 204
    assert _get_org(token, org_id).status_code == 404


def test_admin_cannot_delete_organization() -> None:
    _, _, org_id = _setup_owner("delete-admin-owner")
    _, admin_token = _add_user_with_role(org_id, "admin", "delete-admin")
    assert _delete_org(admin_token, org_id).status_code == 403


def test_member_cannot_delete_organization() -> None:
    _, _, org_id = _setup_owner("delete-member-owner")
    _, member_token = _add_user_with_role(org_id, "member", "delete-member")
    assert _delete_org(member_token, org_id).status_code == 403


def _bot_payload(slug: str, visibility: str = "private") -> dict:
    return {
        "name": "Cascade Bot",
        "slug": slug,
        "description": "",
        "system_prompt": "You are helpful.",
        "welcome_message": "Hi!",
        "language": "en",
        "visibility": visibility,
    }


def test_delete_organization_cascades_all_dependent_data() -> None:
    _, token, org_id = _setup_owner("cascade")

    bot = client.post(
        f"/api/v1/organizations/{org_id}/chatbots",
        json=_bot_payload(_slug("cascade-bot"), visibility="public"),
        headers=_auth(token),
    )
    assert bot.status_code == 201, bot.text
    bot_id = bot.json()["id"]
    assert client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/activate", headers=_auth(token)
    ).status_code == 200

    doc = client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/knowledge/documents",
        json={"name": "Doc", "content": "Some knowledge content.", "source_type": "text"},
        headers=_auth(token),
    )
    assert doc.status_code == 201, doc.text

    conv = client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/conversations",
        json={"title": "Cascade Conversation"},
        headers=_auth(token),
    )
    assert conv.status_code == 201, conv.text
    conv_id = conv.json()["id"]
    chat = client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv_id}/chat",
        json={"content": "Hello"},
        headers=_auth(token),
    )
    assert chat.status_code == 200, chat.text

    widget = client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/widget-config",
        json={"allowed_origins": ["https://example.com"]},
        headers=_auth(token),
    )
    assert widget.status_code == 201, widget.text
    public_key = widget.json()["public_key"]
    session = client.post(
        "/api/v1/public/widget/session",
        json={"public_key": public_key, "origin": "https://example.com"},
    )
    assert session.status_code == 200, session.text

    async def _counts() -> dict[str, int]:
        async with TestSessionLocal() as s:
            counts: dict[str, int] = {}
            for table, col, val in [
                ("memberships", "organization_id", org_id),
                ("chatbots", "organization_id", org_id),
                ("conversations", "organization_id", org_id),
                ("messages", "conversation_id", conv_id),
                ("knowledge_documents", "organization_id", org_id),
                ("document_chunks", "organization_id", org_id),
                ("widget_configs", "chatbot_id", bot_id),
                ("widget_sessions", "chatbot_id", bot_id),
            ]:
                result = await s.execute(
                    text(f"SELECT COUNT(*) FROM {table} WHERE {col} = :v"), {"v": val}
                )
                counts[table] = result.scalar_one()
            return counts

    before = asyncio.run(_counts())
    assert all(v > 0 for v in before.values()), before

    assert _delete_org(token, org_id).status_code == 204

    after = asyncio.run(_counts())
    assert all(v == 0 for v in after.values()), after


def test_delete_organization_does_not_affect_other_organization() -> None:
    _, token_a, org_a = _setup_owner("delete-isolated-a")
    _, token_b, org_b = _setup_owner("delete-isolated-b")
    bot_b = client.post(
        f"/api/v1/organizations/{org_b}/chatbots",
        json=_bot_payload(_slug("untouched-bot")),
        headers=_auth(token_b),
    )
    assert bot_b.status_code == 201, bot_b.text

    assert _delete_org(token_a, org_a).status_code == 204

    assert _get_org(token_b, org_b).status_code == 200
    bots = client.get(f"/api/v1/organizations/{org_b}/chatbots", headers=_auth(token_b))
    assert bots.status_code == 200
    assert len(bots.json()) == 1


# --- 4. Member listing ---


def test_list_members_returns_role_email_and_name() -> None:
    email, token, org_id = _setup_owner("list-members")
    r = _list_members(token, org_id)
    assert r.status_code == 200
    members = r.json()
    assert len(members) == 1
    member = members[0]
    assert member["role"] == "owner"
    assert member["user_email"] == email
    assert member["user_full_name"]
    assert member["user_id"] > 0


def test_list_members_non_member_forbidden() -> None:
    _, _, org_a = _setup_owner("list-members-a")
    _, token_b, _ = _setup_owner("list-members-b")
    assert _list_members(token_b, org_a).status_code == 403


# --- 5. Add member ---


def test_admin_can_add_existing_user_as_member() -> None:
    _, _, org_id = _setup_owner("add-admin-owner")
    _, admin_token = _add_user_with_role(org_id, "admin", "add-admin")
    new_email = _email("addee")
    _register(new_email)
    r = _add_member(admin_token, org_id, new_email, "member")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["role"] == "member"
    assert body["user_email"] == new_email


def test_owner_can_add_owner() -> None:
    _, owner_token, org_id = _setup_owner("add-owner")
    new_email = _email("newowner")
    _register(new_email)
    r = _add_member(owner_token, org_id, new_email, "owner")
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "owner"


def test_admin_cannot_create_owner_membership() -> None:
    _, _, org_id = _setup_owner("add-forbid-owner")
    _, admin_token = _add_user_with_role(org_id, "admin", "add-forbid-admin")
    new_email = _email("forbidowner")
    _register(new_email)
    r = _add_member(admin_token, org_id, new_email, "owner")
    assert r.status_code == 403


def test_add_member_unknown_email_returns_404() -> None:
    _, token, org_id = _setup_owner("add-unknown")
    r = _add_member(token, org_id, _email("does-not-exist"), "member")
    assert r.status_code == 404


def test_add_member_duplicate_returns_409() -> None:
    _, token, org_id = _setup_owner("add-dup-owner")
    dup_email = _email("dup")
    _register(dup_email)
    assert _add_member(token, org_id, dup_email, "member").status_code == 201
    assert _add_member(token, org_id, dup_email, "member").status_code == 409


def test_member_cannot_add_member() -> None:
    _, _, org_id = _setup_owner("add-member-forbid-owner")
    _, member_token = _add_user_with_role(org_id, "member", "add-member-forbid")
    new_email = _email("blocked")
    _register(new_email)
    assert _add_member(member_token, org_id, new_email, "member").status_code == 403


# --- 6. Role changes ---


def test_admin_can_promote_member_to_admin() -> None:
    _, _, org_id = _setup_owner("promote-owner")
    _, admin_token = _add_user_with_role(org_id, "admin", "promote-admin")
    member_email, _ = _add_user_with_role(org_id, "member", "promote-member")
    mid = _mid(org_id, member_email)
    r = _patch_member(admin_token, org_id, mid, "admin")
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


def test_admin_cannot_promote_to_owner() -> None:
    _, _, org_id = _setup_owner("promote-owner-forbid-owner")
    _, admin_token = _add_user_with_role(org_id, "admin", "promote-owner-forbid-admin")
    member_email, _ = _add_user_with_role(org_id, "member", "promote-owner-forbid-member")
    mid = _mid(org_id, member_email)
    assert _patch_member(admin_token, org_id, mid, "owner").status_code == 403


def test_admin_cannot_modify_owner_role() -> None:
    owner_email, _, org_id = _setup_owner("modify-owner-owner")
    _, admin_token = _add_user_with_role(org_id, "admin", "modify-owner-admin")
    owner_mid = _mid(org_id, owner_email)
    assert _patch_member(admin_token, org_id, owner_mid, "admin").status_code == 403


def test_owner_can_promote_to_owner() -> None:
    _, owner_token, org_id = _setup_owner("promote-to-owner")
    member_email, _ = _add_user_with_role(org_id, "member", "promote-to-owner-member")
    mid = _mid(org_id, member_email)
    r = _patch_member(owner_token, org_id, mid, "owner")
    assert r.status_code == 200
    assert r.json()["role"] == "owner"


def test_last_owner_cannot_demote_self() -> None:
    owner_email, owner_token, org_id = _setup_owner("last-owner-demote")
    mid = _mid(org_id, owner_email)
    r = _patch_member(owner_token, org_id, mid, "admin")
    assert r.status_code == 409
    members = _list_members(owner_token, org_id).json()
    assert next(m for m in members if m["id"] == mid)["role"] == "owner"


# --- 7. Removal ---


def test_admin_can_remove_member() -> None:
    _, _, org_id = _setup_owner("remove-member-owner")
    _, admin_token = _add_user_with_role(org_id, "admin", "remove-member-admin")
    member_email, _ = _add_user_with_role(org_id, "member", "remove-member-member")
    mid = _mid(org_id, member_email)
    assert _delete_member(admin_token, org_id, mid).status_code == 204


def test_admin_can_remove_admin() -> None:
    _, _, org_id = _setup_owner("remove-admin-owner")
    _, admin_token = _add_user_with_role(org_id, "admin", "remove-admin-actor")
    other_admin_email, _ = _add_user_with_role(org_id, "admin", "remove-admin-target")
    mid = _mid(org_id, other_admin_email)
    assert _delete_member(admin_token, org_id, mid).status_code == 204


def test_admin_cannot_remove_owner() -> None:
    _, _, org_id = _setup_owner("remove-owner-owner")
    _, admin_token = _add_user_with_role(org_id, "admin", "remove-owner-admin")
    # A second owner keeps this test isolated from the last-owner guard.
    second_owner_email, _ = _add_user_with_role(org_id, "owner", "remove-owner-second")
    mid = _mid(org_id, second_owner_email)
    assert _delete_member(admin_token, org_id, mid).status_code == 403


def test_member_can_remove_self() -> None:
    _, _, org_id = _setup_owner("remove-self-owner")
    member_email, member_token = _add_user_with_role(org_id, "member", "remove-self-member")
    mid = _mid(org_id, member_email)
    assert _delete_member(member_token, org_id, mid).status_code == 204


def test_member_cannot_remove_another_member() -> None:
    _, _, org_id = _setup_owner("remove-other-owner")
    _, member_token = _add_user_with_role(org_id, "member", "remove-other-actor")
    other_email, _ = _add_user_with_role(org_id, "member", "remove-other-target")
    mid = _mid(org_id, other_email)
    assert _delete_member(member_token, org_id, mid).status_code == 403


def test_sole_owner_cannot_remove_self() -> None:
    owner_email, owner_token, org_id = _setup_owner("remove-last-owner")
    mid = _mid(org_id, owner_email)
    r = _delete_member(owner_token, org_id, mid)
    assert r.status_code == 409
    assert _list_members(owner_token, org_id).json()[0]["role"] == "owner"


# --- 8. Cross-tenant isolation ---


def test_cross_tenant_organization_and_member_endpoints_forbidden() -> None:
    owner_a_email, owner_a_token, org_a = _setup_owner("cross-a")
    _, token_b, _ = _setup_owner("cross-b")
    owner_a_mid = _mid(org_a, owner_a_email)

    assert _get_org(token_b, org_a).status_code == 403
    assert _patch_org(token_b, org_a, "Hijacked").status_code == 403
    assert _delete_org(token_b, org_a).status_code == 403
    assert _list_members(token_b, org_a).status_code == 403
    assert _add_member(token_b, org_a, _email("cross-add"), "member").status_code == 403
    assert _patch_member(token_b, org_a, owner_a_mid, "admin").status_code == 403
    assert _delete_member(token_b, org_a, owner_a_mid).status_code == 403

    # Org A and its sole membership are untouched by every rejected attempt.
    assert _get_org(owner_a_token, org_a).status_code == 200
    assert _list_members(owner_a_token, org_a).json()[0]["role"] == "owner"
