"""Streaming chat (SSE) tests — fake provider deterministic stream, RAG,
persistence, security. No network, no API key.

Require Docker PostgreSQL + alembic upgrade head. Run: pytest -m identity
"""

import json
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
    return f"{name}-{_RUN}@example.com"


def _slug(name: str) -> str:
    return f"{name}-{_RUN}"


def _register(email: str, full_name: str = "Stream Tester"):
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


def _setup() -> tuple[str, int, int, int]:
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
        json={"name": "Bot", "slug": _slug(f"bot{uuid.uuid4().hex[:6]}"), "system_prompt": "BE STREAM"},
        headers=_auth(token),
    )
    bot_id = r.json()["id"]
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/conversations",
        json={"title": "C"},
        headers=_auth(token),
    )
    conv_id = r.json()["id"]
    return email, token, org_id, conv_id


def _stream(token: str, org_id: int, conv_id: int, content: str = "Hello", **overrides):
    payload = {"content": content}
    payload.update(overrides)
    return client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv_id}/chat/stream",
        json=payload,
        headers=_auth(token),
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


def _setup_member(org_id: int, role: str = "member") -> str:
    email = _email(f"user{uuid.uuid4().hex[:6]}")
    _register(email)
    token = _login(email)
    import asyncio

    asyncio.run(_set_role(email, org_id, role))
    return token


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


async def _messages(conv_id: int) -> list[tuple[str, str, int]]:
    async with TestSessionLocal() as s:
        r = await s.execute(
            text(
                "SELECT role, content, sequence_number FROM messages "
                "WHERE conversation_id = :cid ORDER BY sequence_number"
            ),
            {"cid": conv_id},
        )
        return [(role, content, seq) for role, content, seq in r.fetchall()]


# --- Success / contract ---


def test_stream_success_events_and_persistence() -> None:
    import asyncio

    _, token, org_id, conv_id = _setup()
    r = _stream(token, org_id, conv_id, "hello stream")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(r.text)
    types = [e for e, _ in events]
    assert "start" in types
    assert "token" in types
    assert len([t for t in types if t == "token"]) >= 1
    assert types[-1] == "end"

    rows = asyncio.run(_messages(conv_id))
    assert [(role, seq) for role, _, seq in rows] == [("user", 1), ("assistant", 2)]
    assert "hello stream" in rows[1][1]


def test_stream_multiple_token_events() -> None:
    _, token, org_id, conv_id = _setup()
    r = _stream(token, org_id, conv_id, "one two three four")
    events = _parse_sse(r.text)
    tokens = [d for t, d in events if t == "token"]
    assert len(tokens) >= 4
    joined = "".join(t["delta"] for t in tokens)
    assert "one two three four" in joined


def test_stream_fake_deterministic() -> None:
    _, token, org_id, conv_a = _setup()
    _, token2, org2, conv_b = _setup()
    a = _parse_sse(_stream(token, org_id, conv_a, "same input").text)
    b = _parse_sse(_stream(token2, org2, conv_b, "same input").text)
    assert [d for t, d in a if t == "token"] == [d for t, d in b if t == "token"]


# --- RAG ---


def test_stream_rag_context_reaches_provider() -> None:
    """Ingest knowledge, stream a matching question; fake provider echoes the
    knowledge context message, proving RAG reached the AI request."""
    email, token, org_id, _ = _setup()
    # create a fresh bot for this test
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots",
        json={"name": "Bot2", "slug": _slug(f"bot2{uuid.uuid4().hex[:6]}"), "system_prompt": "BE STREAM"},
        headers=_auth(token),
    )
    bot_id = r.json()["id"]
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/knowledge/documents",
        json={"name": "D", "content": "stream knowledge marker unique", "source_type": "text"},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/conversations",
        json={"title": "C2"},
        headers=_auth(token),
    )
    conv_id = r.json()["id"]
    sse = _stream(token, org_id, conv_id, "what is stream knowledge marker unique?")
    assert sse.status_code == 200
    joined = "".join(d.get("delta", "") for t, d in _parse_sse(sse.text) if t == "token")
    assert "<knowledge_context>" in joined
    assert "stream knowledge marker unique" in joined


def test_stream_empty_retrieval_works() -> None:
    _, token, org_id, conv_id = _setup()
    sse = _stream(token, org_id, conv_id, "completely unrelated question")
    assert sse.status_code == 200
    events = _parse_sse(sse.text)
    assert events[-1][0] == "end"


# --- Security / lifecycle ---


def test_stream_archived_409() -> None:
    _, token, org_id, conv_id = _setup()
    client.post(f"/api/v1/organizations/{org_id}/conversations/{conv_id}/archive", headers=_auth(token))
    r = _stream(token, org_id, conv_id, "hi")
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["detail"] == "Conversation is archived"


def test_stream_unauthenticated_401() -> None:
    _, _, org_id, conv_id = _setup()
    r = client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv_id}/chat/stream",
        json={"content": "hi"},
    )
    assert r.status_code == 401


def test_stream_wrong_org_denied() -> None:
    _, token_a, org_a, conv_a = _setup()
    _, token_b, org_b, _ = _setup()
    r = _stream(token_b, org_b, conv_a, "hi")
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert events[-1][0] == "error"


def test_stream_member_own_ok_other_denied() -> None:
    _, owner_token, org_id, _ = _setup()
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots",
        json={"name": "Bot3", "slug": _slug(f"bot3{uuid.uuid4().hex[:6]}")},
        headers=_auth(owner_token),
    )
    bot_id = r.json()["id"]
    m1 = _setup_member(org_id, "member")
    m2 = _setup_member(org_id, "member")
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/conversations",
        json={"title": "M1"},
        headers=_auth(m1),
    )
    conv_m1 = r.json()["id"]
    assert _stream(m1, org_id, conv_m1, "hi").status_code == 200
    r2 = _stream(m2, org_id, conv_m1, "hi")
    assert _parse_sse(r2.text)[-1][0] == "error"


def test_stream_invalid_request_422() -> None:
    _, token, org_id, conv_id = _setup()
    assert _stream(token, org_id, conv_id, "hi", provider_id="x").status_code == 422
    assert _stream(token, org_id, conv_id, "").status_code == 422


# --- Provider failures (invalid provider/model) ---


def test_stream_provider_failure_no_assistant() -> None:
    import asyncio

    _, token, org_id, conv_id = _setup()

    async def _set_bad() -> None:
        async with TestSessionLocal() as s:
            await s.execute(
                text(
                    "UPDATE chatbots SET provider_id = 'missing' "
                    "WHERE id = (SELECT chatbot_id FROM conversations WHERE id = :cid)"
                ),
                {"cid": conv_id},
            )
            await s.commit()

    asyncio.run(_set_bad())
    r = _stream(token, org_id, conv_id, "hi")
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert events[-1][0] == "error"
    # User message persisted, no assistant.
    rows = asyncio.run(_messages(conv_id))
    assert [(role, seq) for role, _, seq in rows] == [("user", 1)]


def test_stream_no_secret_or_internal_leak() -> None:
    import asyncio

    _, token, org_id, conv_id = _setup()

    async def _set_bad() -> None:
        async with TestSessionLocal() as s:
            await s.execute(
                text(
                    "UPDATE chatbots SET provider_id = 'missing' "
                    "WHERE id = (SELECT chatbot_id FROM conversations WHERE id = :cid)"
                ),
                {"cid": conv_id},
            )
            await s.commit()

    asyncio.run(_set_bad())
    r = _stream(token, org_id, conv_id, "hi")
    lowered = r.text.lower()
    assert "traceback" not in lowered
    assert "api_key" not in lowered
    assert "sk-" not in lowered
    assert "sqlalchemy" not in lowered
