"""Widget config admin tests — theme/position/avatar CRUD, validation,
avatar upload (content-sniffed, size-capped, replace-not-accumulate), and
path-traversal protection on the avatar-serving route.

Require Docker PostgreSQL + alembic upgrade head. Run: pytest -m identity
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.widget_avatar import upload_dir

pytestmark = pytest.mark.identity

client = TestClient(app)

PASSWORD = "Strong-password-123"
_RUN = uuid.uuid4().hex[:8]

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake but correctly-signed png payload"
JPEG_BYTES = b"\xff\xd8\xff" + b"fake but correctly-signed jpeg payload"
WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"fake but correctly-signed webp payload"
NOT_AN_IMAGE = b"<script>alert(1)</script>this is plainly not image data"


def _email(name: str) -> str:
    return f"{name}-{_RUN}@example.com"


def _slug(name: str) -> str:
    return f"{name}-{_RUN}"


def _register(email: str, full_name: str = "Widget Config Tester"):
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


def _setup_owner_with_bot() -> tuple[str, int, int]:
    email = _email(f"owner{uuid.uuid4().hex[:6]}")
    token = _login(_register(email)["email"])
    org_id = client.post(
        "/api/v1/organizations",
        json={"name": "Org", "slug": _slug(f"org{uuid.uuid4().hex[:6]}")},
        headers=_auth(token),
    ).json()["id"]
    bot_id = client.post(
        f"/api/v1/organizations/{org_id}/chatbots",
        json={"name": "Bot", "slug": _slug(f"bot{uuid.uuid4().hex[:6]}")},
        headers=_auth(token),
    ).json()["id"]
    return token, org_id, bot_id


def _create_config(token: str, org_id: int, bot_id: int, **payload) -> "TestClient.Response":  # type: ignore[name-defined]
    return client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/widget-config",
        json=payload,
        headers=_auth(token),
    )


def _update_config(token: str, org_id: int, bot_id: int, **payload):
    return client.patch(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/widget-config",
        json=payload,
        headers=_auth(token),
    )


def _upload_avatar(token: str, org_id: int, bot_id: int, content: bytes, filename: str, content_type: str):
    return client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/widget-config/avatar",
        files={"file": (filename, content, content_type)},
        headers=_auth(token),
    )


# --- Create / defaults ---


def test_widget_config_defaults_null() -> None:
    token, org_id, bot_id = _setup_owner_with_bot()
    r = _create_config(token, org_id, bot_id)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["theme_color"] is None
    assert body["widget_position"] is None
    assert body["avatar_url"] is None


def test_widget_config_saved_on_create() -> None:
    token, org_id, bot_id = _setup_owner_with_bot()
    r = _create_config(token, org_id, bot_id, theme_color="#2563EB", widget_position="bottom_left")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["theme_color"] == "#2563EB"
    assert body["widget_position"] == "bottom_left"


def test_invalid_theme_color_422() -> None:
    token, org_id, bot_id = _setup_owner_with_bot()
    assert _create_config(token, org_id, bot_id, theme_color="blue").status_code == 422
    assert _create_config(token, org_id, bot_id, theme_color="#fff").status_code == 422
    assert _create_config(token, org_id, bot_id, theme_color="#gggggg").status_code == 422


def test_invalid_widget_position_422() -> None:
    token, org_id, bot_id = _setup_owner_with_bot()
    assert _create_config(token, org_id, bot_id, widget_position="top_left").status_code == 422


# --- Update (new — no path existed before this milestone) ---


def test_widget_config_update() -> None:
    token, org_id, bot_id = _setup_owner_with_bot()
    _create_config(token, org_id, bot_id)
    r = _update_config(token, org_id, bot_id, theme_color="#112233", widget_position="bottom_left")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["theme_color"] == "#112233"
    assert body["widget_position"] == "bottom_left"


def test_widget_config_update_can_clear_back_to_null() -> None:
    token, org_id, bot_id = _setup_owner_with_bot()
    _create_config(token, org_id, bot_id, theme_color="#112233")
    r = _update_config(token, org_id, bot_id, theme_color=None)
    assert r.status_code == 200, r.text
    assert r.json()["theme_color"] is None


def test_widget_config_update_invalid_color_422() -> None:
    token, org_id, bot_id = _setup_owner_with_bot()
    _create_config(token, org_id, bot_id)
    assert _update_config(token, org_id, bot_id, theme_color="not-a-color").status_code == 422


def test_widget_config_update_missing_config_404() -> None:
    token, org_id, bot_id = _setup_owner_with_bot()
    r = _update_config(token, org_id, bot_id, theme_color="#112233")
    assert r.status_code == 404


def test_widget_config_update_cannot_set_avatar_url_directly() -> None:
    """avatar_url is server-set only via the upload endpoint — extra="forbid"
    rejects any attempt to set it through the update payload."""
    token, org_id, bot_id = _setup_owner_with_bot()
    _create_config(token, org_id, bot_id)
    r = client.patch(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/widget-config",
        json={"avatar_url": "/widget-avatars/evil.png"},
        headers=_auth(token),
    )
    assert r.status_code == 422


# --- Avatar upload ---


def test_avatar_upload_png_accepted_and_served() -> None:
    token, org_id, bot_id = _setup_owner_with_bot()
    _create_config(token, org_id, bot_id)
    r = _upload_avatar(token, org_id, bot_id, PNG_BYTES, "avatar.png", "image/png")
    assert r.status_code == 200, r.text
    url = r.json()["avatar_url"]
    assert url is not None and url.startswith("/widget-avatars/")

    served = client.get(url)
    assert served.status_code == 200
    assert served.content == PNG_BYTES


def test_avatar_upload_jpeg_accepted() -> None:
    token, org_id, bot_id = _setup_owner_with_bot()
    _create_config(token, org_id, bot_id)
    r = _upload_avatar(token, org_id, bot_id, JPEG_BYTES, "avatar.jpg", "image/jpeg")
    assert r.status_code == 200, r.text
    assert r.json()["avatar_url"].endswith(".jpg")


def test_avatar_upload_webp_accepted() -> None:
    token, org_id, bot_id = _setup_owner_with_bot()
    _create_config(token, org_id, bot_id)
    r = _upload_avatar(token, org_id, bot_id, WEBP_BYTES, "avatar.webp", "image/webp")
    assert r.status_code == 200, r.text
    assert r.json()["avatar_url"].endswith(".webp")


def test_avatar_upload_wrong_type_disguised_as_image_rejected() -> None:
    """A non-image file with an image extension and an image Content-Type
    must still be rejected — validation is content-based, not
    extension/Content-Type-based."""
    token, org_id, bot_id = _setup_owner_with_bot()
    _create_config(token, org_id, bot_id)
    r = _upload_avatar(token, org_id, bot_id, NOT_AN_IMAGE, "avatar.png", "image/png")
    assert r.status_code == 422, r.text


def test_avatar_upload_oversized_rejected() -> None:
    token, org_id, bot_id = _setup_owner_with_bot()
    _create_config(token, org_id, bot_id)
    oversized = PNG_BYTES + b"\x00" * (settings.widget_avatar_max_bytes)
    assert len(oversized) > settings.widget_avatar_max_bytes
    r = _upload_avatar(token, org_id, bot_id, oversized, "avatar.png", "image/png")
    assert r.status_code == 413, r.text


def test_avatar_upload_replaces_old_file_not_orphaned() -> None:
    token, org_id, bot_id = _setup_owner_with_bot()
    _create_config(token, org_id, bot_id)
    first = _upload_avatar(token, org_id, bot_id, PNG_BYTES, "a.png", "image/png").json()
    first_url = first["avatar_url"]
    first_path = upload_dir() / first_url.split("/")[-1]
    assert first_path.is_file()

    second = _upload_avatar(token, org_id, bot_id, JPEG_BYTES, "b.jpg", "image/jpeg").json()
    second_url = second["avatar_url"]
    assert second_url != first_url

    assert not first_path.is_file(), "old avatar file must be deleted, not orphaned"
    second_path = upload_dir() / second_url.split("/")[-1]
    assert second_path.is_file()


def test_avatar_upload_missing_config_404() -> None:
    token, org_id, bot_id = _setup_owner_with_bot()
    r = _upload_avatar(token, org_id, bot_id, PNG_BYTES, "a.png", "image/png")
    assert r.status_code == 404


# --- Avatar serving: path traversal ---


def test_avatar_serving_rejects_path_traversal() -> None:
    for attempt in (
        "..%2F..%2F..%2Fapp%2Fmain.py",
        "..%2f..%2fapp%2fmain.py",
        "%2e%2e%2f%2e%2e%2fapp%2fmain.py",
        "....//....//app/main.py",
    ):
        r = client.get(f"/widget-avatars/{attempt}", follow_redirects=False)
        assert r.status_code == 404, f"{attempt!r} -> {r.status_code}"
        assert "FastAPI" not in r.text and "import" not in r.text


def test_avatar_serving_rejects_malformed_filename() -> None:
    assert client.get("/widget-avatars/not-a-real-filename.png").status_code == 404
    assert client.get("/widget-avatars/" + "a" * 32 + ".exe").status_code == 404
    assert client.get("/widget-avatars/" + "a" * 31 + ".png").status_code == 404


# --- Public key belongs to chatbot, not org-guessable ---


def test_widget_config_cannot_be_created_for_other_org_bot() -> None:
    token_a, org_a, bot_a = _setup_owner_with_bot()
    token_b, org_b, _ = _setup_owner_with_bot()
    r = _create_config(token_b, org_a, bot_a)
    assert r.status_code == 403
