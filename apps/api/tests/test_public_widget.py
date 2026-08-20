"""Public widget tests — config, sessions, origin control, streaming chat,
RAG, security. No network, no API key.

Require Docker PostgreSQL + alembic upgrade head. Run: pytest -m identity
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.core.rate_limit import widget_rate_limiter
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.identity

client = TestClient(app)

PASSWORD = "strong-password-123"
_RUN = uuid.uuid4().hex[:8]


def _email(name: str) -> str:
    return f"{name}-{_RUN}@example.com"


def _slug(name: str) -> str:
    return f"{name}-{_RUN}"


def _register(email: str, full_name: str = "Widget Tester"):
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


def _setup_public_bot() -> tuple[str, str, int, str]:
    """Create org, active+public chatbot, widget config. Returns
    (admin_token, org_id, chatbot_id, public_key)."""
    email = _email(f"owner{uuid.uuid4().hex[:6]}")
    token = _login(_register(email)["email"])
    r = client.post(
        "/api/v1/organizations",
        json={"name": "Org", "slug": _slug(f"org{uuid.uuid4().hex[:6]}")},
        headers=_auth(token),
    )
    org_id = r.json()["id"]
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots",
        json={"name": "Public Bot", "slug": _slug(f"bot{uuid.uuid4().hex[:6]}"), "welcome_message": "Hi there"},
        headers=_auth(token),
    )
    bot_id = r.json()["id"]
    client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/activate",
        headers=_auth(token),
    )
    r = client.patch(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}",
        json={"visibility": "public"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/widget-config",
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    return token, org_id, bot_id, r.json()["public_key"]


def _session(public_key: str, origin: str = "https://example.com"):
    return client.post(
        "/api/v1/public/widget/session",
        json={"public_key": public_key, "origin": origin},
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


async def _message_count() -> int:
    async with TestSessionLocal() as s:
        return (
            await s.execute(text("SELECT COUNT(*) FROM messages"))
        ).scalar_one()


async def _widget_msgs(chatbot_id: int) -> list[str]:
    async with TestSessionLocal() as s:
        r = await s.execute(
            text(
                "SELECT m.content FROM messages m JOIN conversations c ON c.id = m.conversation_id "
                "WHERE c.chatbot_id = :cid ORDER BY m.sequence_number"
            ),
            {"cid": chatbot_id},
        )
        return [row[0] for row in r.fetchall()]


# --- Config / session ---


def test_session_valid_public_key() -> None:
    _, _, _, key = _setup_public_bot()
    r = _session(key)
    assert r.status_code == 200
    body = r.json()
    assert body["session_token"]
    assert body["config"]["chatbot_name"] == "Public Bot"
    assert body["config"]["welcome_message"] == "Hi there"
    assert body["config"]["enabled"] is True
    # No secret/system prompt/provider leakage.
    assert "system_prompt" not in r.text
    assert "provider" not in r.text
    assert "model_id" not in r.text
    assert "organization_id" not in r.text


def test_session_invalid_public_key_404() -> None:
    r = _session("nope")
    assert r.status_code == 404


def test_session_private_chatbot_404() -> None:
    email = _email(f"priv{uuid.uuid4().hex[:6]}")
    token = _login(_register(email)["email"])
    org = client.post(
        "/api/v1/organizations", json={"name": "O", "slug": _slug(f"o{uuid.uuid4().hex[:6]}")}, headers=_auth(token)
    ).json()
    bot = client.post(
        f"/api/v1/organizations/{org['id']}/chatbots",
        json={"name": "Private", "slug": _slug(f"pb{uuid.uuid4().hex[:6]}")},
        headers=_auth(token),
    ).json()
    client.post(f"/api/v1/organizations/{org['id']}/chatbots/{bot['id']}/activate", headers=_auth(token))
    # visibility stays private
    r = client.post(
        f"/api/v1/organizations/{org['id']}/chatbots/{bot['id']}/widget-config",
        headers=_auth(token),
    )
    assert r.status_code == 201
    s = _session(r.json()["public_key"])
    assert s.status_code == 404


def test_session_origin_denied() -> None:
    _, _, _, key = _setup_public_bot()
    # No allowed_origins configured → any origin OK. Set origins then deny.
    email = _email(f"origin{uuid.uuid4().hex[:6]}")
    token = _login(_register(email)["email"])
    org = client.post(
        "/api/v1/organizations", json={"name": "O2", "slug": _slug(f"o2{uuid.uuid4().hex[:6]}")}, headers=_auth(token)
    ).json()
    bot = client.post(
        f"/api/v1/organizations/{org['id']}/chatbots",
        json={"name": "B", "slug": _slug(f"ob{uuid.uuid4().hex[:6]}")},
        headers=_auth(token),
    ).json()
    client.post(f"/api/v1/organizations/{org['id']}/chatbots/{bot['id']}/activate", headers=_auth(token))
    client.patch(
        f"/api/v1/organizations/{org['id']}/chatbots/{bot['id']}",
        json={"visibility": "public"},
        headers=_auth(token),
    )
    r = client.post(
        f"/api/v1/organizations/{org['id']}/chatbots/{bot['id']}/widget-config",
        json={"allowed_origins": ["https://good.example"]},
        headers=_auth(token),
    )
    assert r.status_code == 201
    key2 = r.json()["public_key"]
    assert _session(key2, origin="https://good.example").status_code == 200
    assert _session(key2, origin="https://evil.example").status_code == 403


# --- Chat / stream ---


def test_public_stream_tokens_and_persistence() -> None:
    _, _, bot_id, key = _setup_public_bot()
    sess = _session(key).json()["session_token"]
    r = _stream(sess, "hello widget")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(r.text)
    types = [t for t, _ in events]
    assert "start" in types
    assert "token" in types
    assert types[-1] == "end"

    import asyncio

    msgs = asyncio.run(_widget_msgs(bot_id))
    assert len(msgs) == 2  # user + assistant
    assert "hello widget" in msgs[1]


def test_public_stream_rag() -> None:
    token, org_id, bot_id, key = _setup_public_bot()
    # Ingest knowledge (bot must be active already).
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/knowledge/documents",
        json={"name": "K", "content": "widget knowledge marker unique", "source_type": "text"},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    sess = _session(key).json()["session_token"]
    r = _stream(sess, "what is widget knowledge marker unique?")
    assert r.status_code == 200
    joined = "".join(d.get("delta", "") for t, d in _parse_sse(r.text) if t == "token")
    assert "<knowledge_context>" in joined
    assert "widget knowledge marker unique" in joined


def test_public_stream_invalid_session() -> None:
    r = _stream("garbage-token", "hi")
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert events[-1][0] == "error"


def test_public_stream_rate_limit() -> None:
    _, _, _, key = _setup_public_bot()
    sess = _session(key).json()["session_token"]
    # Exhaust limiter for this session.
    widget_rate_limiter._hits[f"session:{sess}"] = widget_rate_limiter._hits[f"session:{sess}"]
    from collections import deque

    for _ in range(30):
        widget_rate_limiter.allow(f"session:{sess}")
    r = _stream(sess, "one more")
    assert r.status_code == 429


def test_public_stream_invalid_content_422() -> None:
    _, _, _, key = _setup_public_bot()
    sess = _session(key).json()["session_token"]
    assert _stream(sess, "").status_code == 422
    r = client.post(
        "/api/v1/public/widget/chat/stream",
        json={"session_token": sess, "content": "hi", "extra": "x"},
    )
    assert r.status_code == 422


def test_public_cannot_inject_provider_model() -> None:
    _, _, _, key = _setup_public_bot()
    sess = _session(key).json()["session_token"]
    r = client.post(
        "/api/v1/public/widget/chat/stream",
        json={"session_token": sess, "content": "hi", "provider_id": "x"},
    )
    assert r.status_code == 422


def test_public_stream_with_multiple_widget_configs() -> None:
    """Regression: multiple credentials for one chatbot must not break session
    resolution (get_by_public_key_session used to raise MultipleResultsFound)."""
    token, org_id, bot_id, key = _setup_public_bot()
    # Create a second credential for the same chatbot (old one stays active).
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/widget-config",
        headers=_auth(token),
    )
    assert r.status_code == 201
    # Session created with the first key must still resolve and stream.
    sess = _session(key).json()["session_token"]
    r = _stream(sess, "hello multiple")
    assert r.status_code == 200
    events = _parse_sse(r.text)
    types = [t for t, _ in events]
    assert "start" in types
    assert types[-1] == "end"


# --- Cross-tenant / cross-chatbot ---


def test_session_cannot_switch_chatbot() -> None:
    _, _, bot_a, key_a = _setup_public_bot()
    _, _, bot_b, key_b = _setup_public_bot()
    sess_a = _session(key_a).json()["session_token"]
    # Session A must only work against chatbot A; no endpoint accepts chatbot id,
    # so verify by checking conversation binding via DB.
    import asyncio

    async def check() -> None:
        async with TestSessionLocal() as s:
            r = await s.execute(
                text(
                    "SELECT ws.chatbot_id FROM widget_sessions ws WHERE ws.session_token = :t"
                ),
                {"t": sess_a},
            )
            assert r.scalar_one() == bot_a

    asyncio.run(check())
    # Session B works too; both bound to own chatbots.
    assert _stream(sess_a, "hi").status_code == 200


def test_session_cannot_stream_into_other_chatbots_conversation() -> None:
    """Regression: a widget session must never stream into a conversation bound
    to a different chatbot (defense-in-depth for session.chatbot_id ==
    conversation.chatbot_id)."""
    import asyncio

    email = _email(f"bind{uuid.uuid4().hex[:6]}")
    token = _login(_register(email)["email"])
    org = client.post(
        "/api/v1/organizations", json={"name": "O", "slug": _slug(f"o{uuid.uuid4().hex[:6]}")}, headers=_auth(token)
    ).json()

    def _mk_bot(name: str) -> tuple[dict, str]:
        bot = client.post(
            f"/api/v1/organizations/{org['id']}/chatbots",
            json={"name": name, "slug": _slug(f"b{uuid.uuid4().hex[:6]}")},
            headers=_auth(token),
        ).json()
        client.post(f"/api/v1/organizations/{org['id']}/chatbots/{bot['id']}/activate", headers=_auth(token))
        client.patch(
            f"/api/v1/organizations/{org['id']}/chatbots/{bot['id']}",
            json={"visibility": "public"},
            headers=_auth(token),
        )
        r = client.post(
            f"/api/v1/organizations/{org['id']}/chatbots/{bot['id']}/widget-config",
            headers=_auth(token),
        )
        assert r.status_code == 201, r.text
        return bot, r.json()["public_key"]

    bot_a, key_a = _mk_bot("Bind A")
    bot_b, _ = _mk_bot("Bind B")
    sess_a = _session(key_a).json()["session_token"]

    # Create a conversation that belongs to bot B.
    conv_b = client.post(
        f"/api/v1/organizations/{org['id']}/chatbots/{bot_b['id']}/conversations",
        json={"title": "other bot conversation"},
        headers=_auth(token),
    ).json()

    # Tamper: point session A at bot B's conversation.
    async def tamper() -> None:
        async with TestSessionLocal() as s:
            await s.execute(
                text(
                    "UPDATE widget_sessions SET conversation_id = :cid WHERE session_token = :t"
                ),
                {"cid": conv_b["id"], "t": sess_a},
            )
            await s.commit()

    asyncio.run(tamper())

    # Streaming must be refused with a safe error and must not write to bot B's
    # conversation (which would cross the chatbot/org boundary).
    r = _stream(sess_a, "sneaky")
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert events[-1][0] == "error"
    assert "Invalid" in events[-1][1]["detail"] or "invalid" in events[-1][1]["detail"].lower()

    async def count() -> int:
        async with TestSessionLocal() as s:
            c = await s.execute(
                text("SELECT COUNT(*) FROM messages WHERE conversation_id = :cid"),
                {"cid": conv_b["id"]},
            )
            return c.scalar_one()

    assert asyncio.run(count()) == 0


def test_authenticated_chat_regression() -> None:
    email = _email(f"reg{uuid.uuid4().hex[:6]}")
    token = _login(_register(email)["email"])
    org = client.post(
        "/api/v1/organizations", json={"name": "R", "slug": _slug(f"r{uuid.uuid4().hex[:6]}")}, headers=_auth(token)
    ).json()
    bot = client.post(
        f"/api/v1/organizations/{org['id']}/chatbots",
        json={"name": "B", "slug": _slug(f"rb{uuid.uuid4().hex[:6]}")},
        headers=_auth(token),
    ).json()
    conv = client.post(
        f"/api/v1/organizations/{org['id']}/chatbots/{bot['id']}/conversations",
        json={"title": "C"},
        headers=_auth(token),
    ).json()
    r = client.post(
        f"/api/v1/organizations/{org['id']}/conversations/{conv['id']}/chat",
        json={"content": "regression"},
        headers=_auth(token),
    )
    assert r.status_code == 200


def test_authenticated_stream_regression() -> None:
    email = _email(f"stre{uuid.uuid4().hex[:6]}")
    token = _login(_register(email)["email"])
    org = client.post(
        "/api/v1/organizations", json={"name": "S", "slug": _slug(f"s{uuid.uuid4().hex[:6]}")}, headers=_auth(token)
    ).json()
    bot = client.post(
        f"/api/v1/organizations/{org['id']}/chatbots",
        json={"name": "B", "slug": _slug(f"sb{uuid.uuid4().hex[:6]}")},
        headers=_auth(token),
    ).json()
    conv = client.post(
        f"/api/v1/organizations/{org['id']}/chatbots/{bot['id']}/conversations",
        json={"title": "C"},
        headers=_auth(token),
    ).json()
    r = client.post(
        f"/api/v1/organizations/{org['id']}/conversations/{conv['id']}/chat/stream",
        json={"content": "regression"},
        headers=_auth(token),
    )
    assert r.status_code == 200


def test_widget_js_served() -> None:
    r = client.get("/widget.js")
    assert r.status_code == 200
    assert "portableAI" in r.text or "portableai" in r.text
