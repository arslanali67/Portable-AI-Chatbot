"""Refresh-token rotation, logout, and password-reset tests.

Require Docker PostgreSQL + identity tables. Run: pytest -m identity
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.security import generate_token, hash_token
from app.main import app
from app.models import PasswordResetToken, User
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.identity

client = TestClient(app)

PASSWORD = "strong-password-123"
REFRESH_COOKIE = "portableai_refresh_token"
_RUN = uuid.uuid4().hex[:8]


def _email(name: str) -> str:
    return f"{name}-{_RUN}@example.com"


def _register(email: str, password: str = PASSWORD) -> dict:
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Session Tester"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _login(email: str, password: str = PASSWORD):
    client.cookies.clear()
    r = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return r


def _refresh(raw_token: str):
    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE, raw_token)
    return client.post("/api/v1/auth/refresh")


def _logout(raw_token: str):
    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE, raw_token)
    return client.post("/api/v1/auth/logout")


async def _insert_reset_token(
    user_id: int, *, expired: bool = False, used: bool = False
) -> str:
    raw = generate_token()
    async with TestSessionLocal() as session:
        expires_at = datetime.now(timezone.utc) + (
            timedelta(minutes=-5) if expired else timedelta(hours=1)
        )
        token = PasswordResetToken(
            user_id=user_id,
            token_hash=hash_token(raw),
            expires_at=expires_at,
            used_at=datetime.now(timezone.utc) if used else None,
        )
        session.add(token)
        await session.commit()
    return raw


async def _reset_token_count(user_id: int) -> int:
    from sqlalchemy import func, select

    async with TestSessionLocal() as session:
        result = await session.execute(
            select(func.count())
            .select_from(PasswordResetToken)
            .where(PasswordResetToken.user_id == user_id)
        )
        return result.scalar_one()


async def _get_user_by_email(email: str) -> User | None:
    from sqlalchemy import select

    async with TestSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()


# --- Login / refresh cookie issuance ---


def test_login_issues_access_token_and_refresh_cookie() -> None:
    email = _email("login")
    _register(email)
    r = _login(email)
    body = r.json()
    assert "access_token" in body and body["access_token"]
    raw_refresh = r.cookies.get(REFRESH_COOKIE)
    assert raw_refresh, "login must set a refresh-token cookie"


# --- Rotation ---


def test_refresh_rotates_and_old_token_stops_working() -> None:
    email = _email("rotate")
    _register(email)
    login_resp = _login(email)
    token_0 = login_resp.cookies.get(REFRESH_COOKIE)

    r1 = _refresh(token_0)
    assert r1.status_code == 200, r1.text
    token_1 = r1.cookies.get(REFRESH_COOKIE)
    assert token_1 and token_1 != token_0

    # New access token actually works against a protected route.
    new_access = r1.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me.status_code == 200

    # The rotated-out token is now dead.
    reuse = _refresh(token_0)
    assert reuse.status_code == 401


def test_refresh_token_reuse_revokes_entire_family() -> None:
    """Adversarial: rotate twice, then replay the FIRST (already-rotated)
    token. That must kill the whole family — including the second/newest
    token, which was never itself reused or expired."""
    email = _email("reuse")
    _register(email)
    login_resp = _login(email)
    token_0 = login_resp.cookies.get(REFRESH_COOKIE)

    r1 = _refresh(token_0)
    assert r1.status_code == 200, r1.text
    token_1 = r1.cookies.get(REFRESH_COOKIE)

    r2 = _refresh(token_1)
    assert r2.status_code == 200, r2.text
    token_2 = r2.cookies.get(REFRESH_COOKIE)

    # Replay the FIRST token (already rotated out at step r1) — theft signal.
    replay = _refresh(token_0)
    assert replay.status_code == 401

    # The newest, never-reused token must ALSO be dead now — proving the
    # whole family was revoked, not just token_0's own row.
    still_dead = _refresh(token_2)
    assert still_dead.status_code == 401


# --- Logout ---


def test_logout_revokes_current_family() -> None:
    email = _email("logout")
    _register(email)
    login_resp = _login(email)
    token_0 = login_resp.cookies.get(REFRESH_COOKIE)

    out = _logout(token_0)
    assert out.status_code == 204

    after = _refresh(token_0)
    assert after.status_code == 401


def test_logout_with_no_cookie_is_a_no_op_204() -> None:
    client.cookies.clear()
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 204


# --- Password reset request: enumeration safety + rate limiting ---


def test_password_reset_request_identical_for_existing_and_unknown_email() -> None:
    email = _email("resetreq")
    _register(email)

    existing = client.post("/api/v1/auth/password-reset/request", json={"email": email})
    unknown = client.post(
        "/api/v1/auth/password-reset/request", json={"email": _email("does-not-exist")}
    )

    assert existing.status_code == unknown.status_code == 204
    assert existing.text == unknown.text == ""


def test_password_reset_request_email_call_gated_on_real_account_response_stays_identical() -> None:
    """The most important test in this milestone: with real email delivery
    mocked (not the log-only stub), confirm the send function is called
    only when the account genuinely exists, while the HTTP response stays
    byte-identical either way — enumeration safety is unaffected by
    switching from log-only to real delivery."""
    email = _email("emailgate")
    _register(email)
    unknown_email = _email("emailgate-unknown")

    with patch(
        "app.services.email.EmailService.send_password_reset_email", new_callable=AsyncMock
    ) as mock_send:
        mock_send.return_value = True
        existing_resp = client.post("/api/v1/auth/password-reset/request", json={"email": email})
        unknown_resp = client.post(
            "/api/v1/auth/password-reset/request", json={"email": unknown_email}
        )

    assert existing_resp.status_code == unknown_resp.status_code == 204
    assert existing_resp.text == unknown_resp.text == ""
    # The core proof: exactly one send, for the real account only.
    mock_send.assert_called_once()
    assert mock_send.call_args.kwargs["to_email"] == email


def test_password_reset_request_email_contains_recipient_and_a_working_raw_token() -> None:
    email = _email("emailcontent")
    _register(email)

    with patch(
        "app.services.email.EmailService.send_password_reset_email", new_callable=AsyncMock
    ) as mock_send:
        mock_send.return_value = True
        r = client.post("/api/v1/auth/password-reset/request", json={"email": email})
    assert r.status_code == 204

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["to_email"] == email
    assert "token=" in call_kwargs["reset_url"]
    raw_token = call_kwargs["reset_url"].split("token=", 1)[1]

    # Prove it's the genuine, usable raw token — not a placeholder — by
    # actually completing a reset with it.
    confirm = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw_token, "new_password": "brand-new-password-456"},
    )
    assert confirm.status_code == 204


def test_password_reset_request_resend_failure_still_generic_response() -> None:
    """If the Resend call itself fails, the response must stay exactly the
    same generic shape — a delivery failure must never leak into the HTTP
    response or break enumeration safety."""
    email = _email("resendfail")
    _register(email)

    with patch(
        "app.services.email.EmailService.send_password_reset_email", new_callable=AsyncMock
    ) as mock_send:
        mock_send.return_value = False  # simulated Resend failure
        r = client.post("/api/v1/auth/password-reset/request", json={"email": email})

    assert r.status_code == 204
    assert r.text == ""
    mock_send.assert_called_once()


def test_password_reset_request_is_rate_limited() -> None:
    email = _email("resetrate")
    user = _register(email)

    # Rate limiter allows 5/hr for this key; fire 8 requests.
    for _ in range(8):
        r = client.post("/api/v1/auth/password-reset/request", json={"email": email})
        assert r.status_code == 204  # always the same generic response

    # Only the first 5 should have actually created a token row — the rest
    # were silently rate-limited (verified via direct DB count, since the
    # HTTP response is deliberately identical either way).
    count = asyncio.run(_reset_token_count(user["id"]))
    assert count == 5


# --- Password reset confirm ---


def test_password_reset_confirm_succeeds_sets_password_and_revokes_sessions() -> None:
    email = _email("resetconfirm")
    user = _register(email)
    login_resp = _login(email)
    old_refresh = login_resp.cookies.get(REFRESH_COOKIE)

    raw_reset = asyncio.run(_insert_reset_token(user["id"]))
    new_password = "brand-new-password-456"
    confirm = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw_reset, "new_password": new_password},
    )
    assert confirm.status_code == 204

    # Old password rejected, new password works.
    old_login = client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/v1/auth/login", data={"username": email, "password": new_password}
    )
    assert new_login.status_code == 200

    # The refresh token issued BEFORE the reset must no longer work.
    stale = _refresh(old_refresh)
    assert stale.status_code == 401


def test_password_reset_confirm_rejects_expired_token() -> None:
    email = _email("resetexpired")
    user = _register(email)
    raw_reset = asyncio.run(_insert_reset_token(user["id"], expired=True))

    r = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw_reset, "new_password": "whatever-new-pass"},
    )
    assert r.status_code == 400


def test_password_reset_confirm_rejects_already_used_token() -> None:
    email = _email("resetused")
    user = _register(email)
    raw_reset = asyncio.run(_insert_reset_token(user["id"], used=True))

    r = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw_reset, "new_password": "whatever-new-pass"},
    )
    assert r.status_code == 400


def test_password_reset_confirm_rejects_unknown_token() -> None:
    r = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "not-a-real-token", "new_password": "whatever-new-pass"},
    )
    assert r.status_code == 400
