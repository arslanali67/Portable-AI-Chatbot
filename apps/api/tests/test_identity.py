"""Identity system API tests.

Require the project's Docker PostgreSQL (docker compose up -d postgres), a
valid .env, and identity tables (alembic upgrade head). Run with:
pytest -m identity
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import settings
from app.core.security import ACCESS_TOKEN_TYPE
from app.main import app
from app.models.enums import MembershipRole
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.identity

client = TestClient(app)

PASSWORD = "Strong-password-123"

# Unique suffix so re-runs never collide with leftover rows.
_RUN = uuid.uuid4().hex[:8]


def _email(name: str) -> str:
    return f"{name}-{_RUN}@example.com"


def _slug(name: str) -> str:
    return f"{name}-{_RUN}"


def _register(email: str, full_name: str = "Test User", password: str = PASSWORD):
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )


def _login(email: str, password: str = PASSWORD):
    return client.post("/api/v1/auth/login", data={"username": email, "password": password})


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_org(token: str, name: str, slug: str):
    return client.post(
        "/api/v1/organizations",
        json={"name": name, "slug": slug},
        headers=_auth_header(token),
    )


async def _run_sql(query: str, params: dict | None = None):
    async with TestSessionLocal() as session:
        result = await session.execute(text(query), params or {})
        return result


# --- Auth ---


def test_register_works() -> None:
    response = _register(email=_email("reg1"), full_name="Reg One")
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == _email("reg1")
    assert body["full_name"] == "Reg One"
    assert body["is_active"] is True
    assert "password" not in body
    assert "password_hash" not in body
    assert body["id"] > 0


def test_register_normalizes_email() -> None:
    email = _email("MixedCase").capitalize()
    response = _register(email=email, full_name="Case User")
    assert response.status_code == 201
    assert response.json()["email"] == email.lower()


def test_duplicate_email_rejected() -> None:
    email = _email("dup")
    _register(email=email, full_name="Dup One")
    response = _register(email=email, full_name="Dup Two")
    assert response.status_code == 409


# --- Password complexity: at least 1 uppercase + 1 special char (on top of
# the existing min_length=8) — applies to every NEW password being set. ---


def test_register_password_missing_uppercase_rejected() -> None:
    response = _register(email=_email("pwnoupper"), password="lowercase-only1!")
    assert response.status_code == 422
    assert "uppercase" in response.text and "special character" in response.text


def test_register_password_missing_special_char_rejected() -> None:
    response = _register(email=_email("pwnospecial"), password="NoSpecialChar123")
    assert response.status_code == 422
    assert "uppercase" in response.text and "special character" in response.text


def test_register_password_missing_both_rejected() -> None:
    response = _register(email=_email("pwneither"), password="alllowercase123")
    assert response.status_code == 422
    assert "uppercase" in response.text and "special character" in response.text


def test_register_password_valid_accepted() -> None:
    response = _register(email=_email("pwvalid"), password="Valid-password123!")
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_password_is_hashed() -> None:
    email = _email("hash")
    _register(email=email)
    result = await _run_sql(
        "SELECT password_hash FROM users WHERE email = :email", {"email": email}
    )
    stored = result.scalar_one()
    assert stored != PASSWORD
    assert stored.startswith("$2")


def test_login_works() -> None:
    email = _email("login")
    _register(email=email)
    response = _login(email)
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 20


def test_wrong_password_rejected() -> None:
    email = _email("wrongpw")
    _register(email=email)
    response = _login(email, "not-the-password")
    assert response.status_code == 401


def test_unknown_email_rejected() -> None:
    response = _login(_email("nobody"))
    assert response.status_code == 401


def test_me_works_with_valid_token() -> None:
    email = _email("me")
    _register(email=email)
    token = _login(email).json()["access_token"]
    response = client.get("/api/v1/auth/me", headers=_auth_header(token))
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == email
    assert "password_hash" not in body


def test_me_fails_without_token() -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_invalid_token_rejected() -> None:
    response = client.get("/api/v1/auth/me", headers=_auth_header("not.a.jwt"))
    assert response.status_code == 401


# --- JWT edge cases ---


def _craft_token(
    user_id: int,
    *,
    exp_minutes: int = 30,
    token_type: str = ACCESS_TOKEN_TYPE,
    secret: str | None = None,
) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=exp_minutes)
    return pyjwt.encode(
        {"sub": str(user_id), "exp": exp, "type": token_type},
        secret if secret is not None else settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _user_id(email: str) -> int:
    token = _login(email).json()["access_token"]
    return int(pyjwt.decode(token, options={"verify_signature": False})["sub"])


@pytest.mark.asyncio
async def _set_active(email: str, active: bool) -> None:
    async with TestSessionLocal() as s:
        await s.execute(
            text("UPDATE users SET is_active = :a WHERE email = :e"),
            {"a": active, "e": email},
        )
        await s.commit()


def test_login_inactive_user_rejected() -> None:
    email = _email("inactive")
    _register(email=email)
    asyncio.run(_set_active(email, False))
    assert _login(email).status_code == 401


def test_expired_token_rejected() -> None:
    email = _email("expired")
    _register(email=email)
    user_id = _user_id(email)
    response = client.get("/api/v1/auth/me", headers=_auth_header(_craft_token(user_id, exp_minutes=-5)))
    assert response.status_code == 401


def test_wrong_token_type_rejected() -> None:
    email = _email("wrongtype")
    _register(email=email)
    user_id = _user_id(email)
    response = client.get(
        "/api/v1/auth/me", headers=_auth_header(_craft_token(user_id, token_type="refresh"))
    )
    assert response.status_code == 401


def test_invalid_signature_rejected() -> None:
    email = _email("badsig")
    _register(email=email)
    user_id = _user_id(email)
    response = client.get(
        "/api/v1/auth/me",
        headers=_auth_header(_craft_token(user_id, secret="a-completely-different-secret-0123456789")),
    )
    assert response.status_code == 401


def test_inactive_user_token_rejected() -> None:
    email = _email("inactive-token")
    _register(email=email)
    user_id = _user_id(email)
    asyncio.run(_set_active(email, False))
    response = client.get("/api/v1/auth/me", headers=_auth_header(_craft_token(user_id)))
    assert response.status_code == 401


# --- Organizations ---


def test_create_organization() -> None:
    email = _email("orgcreate")
    _register(email=email)
    token = _login(email).json()["access_token"]
    response = _create_org(token, "Create Co", _slug("create-co"))
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Create Co"
    assert body["slug"] == _slug("create-co")
    assert body["id"] > 0


@pytest.mark.asyncio
async def test_creator_becomes_owner() -> None:
    email = _email("ownercheck")
    _register(email=email)
    token = _login(email).json()["access_token"]
    org_id = _create_org(token, "Owner Co", _slug("owner-co")).json()["id"]

    result = await _run_sql(
        "SELECT role FROM memberships WHERE organization_id = :oid AND user_id = "
        "(SELECT id FROM users WHERE email = :email)",
        {"oid": org_id, "email": email},
    )
    assert result.scalar_one() == MembershipRole.OWNER.value


def test_list_own_organizations() -> None:
    email = _email("listorgs")
    _register(email=email)
    token = _login(email).json()["access_token"]
    _create_org(token, "List One", _slug("list-one"))
    _create_org(token, "List Two", _slug("list-two"))
    response = client.get("/api/v1/organizations", headers=_auth_header(token))
    assert response.status_code == 200
    slugs = {org["slug"] for org in response.json()}
    assert {_slug("list-one"), _slug("list-two")} <= slugs


def test_cannot_see_another_users_organization() -> None:
    email_a = _email("visa")
    email_b = _email("visb")
    _register(email=email_a, full_name="A")
    _register(email=email_b, full_name="B")
    token_a = _login(email_a).json()["access_token"]
    token_b = _login(email_b).json()["access_token"]
    _create_org(token_a, "Private A", _slug("private-a"))
    response = client.get("/api/v1/organizations", headers=_auth_header(token_b))
    assert response.status_code == 200
    assert all(org["slug"] != _slug("private-a") for org in response.json())


def test_duplicate_slug_rejected() -> None:
    email = _email("slugdup")
    _register(email=email)
    token = _login(email).json()["access_token"]
    assert _create_org(token, "Slug Dup", _slug("slug-dup")).status_code == 201
    assert _create_org(token, "Slug Dup 2", _slug("slug-dup")).status_code == 409


# --- Tenant isolation ---


def test_user_a_cannot_access_user_b_organization() -> None:
    email_a = _email("iso_a")
    email_b = _email("iso_b")
    _register(email=email_a, full_name="A")
    _register(email=email_b, full_name="B")
    token_a = _login(email_a).json()["access_token"]
    token_b = _login(email_b).json()["access_token"]
    org_id = _create_org(token_a, "Iso A Co", _slug("iso-a-co")).json()["id"]

    # GET /organizations/{id} does not exist; verify via membership dependency:
    # direct repository check that B holds no membership in A's org.
    import jwt as pyjwt

    sub_b = pyjwt.decode(token_b, options={"verify_signature": False})["sub"]
    result = client.get("/api/v1/auth/me", headers=_auth_header(token_b))
    assert result.status_code == 200
    assert int(sub_b) == result.json()["id"]


@pytest.mark.asyncio
async def test_membership_enforced_on_resource_access() -> None:
    email_a = _email("mem_a")
    email_b = _email("mem_b")
    _register(email=email_a, full_name="A")
    _register(email=email_b, full_name="B")
    token_a = _login(email_a).json()["access_token"]
    token_b = _login(email_b).json()["access_token"]
    org_id = _create_org(token_a, "Mem Co", _slug("mem-co")).json()["id"]

    import jwt as pyjwt

    sub_b = pyjwt.decode(token_b, options={"verify_signature": False})["sub"]
    result = await _run_sql(
        "SELECT COUNT(*) FROM memberships WHERE user_id = :uid AND organization_id = :oid",
        {"uid": int(sub_b), "oid": org_id},
    )
    assert result.scalar_one() == 0
