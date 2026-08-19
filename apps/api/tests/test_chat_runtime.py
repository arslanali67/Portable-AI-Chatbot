"""Chat runtime tests — one turn: user message → fake gateway → assistant
message. Deterministic, no network (FakeAIProvider).

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


def _register(email: str, full_name: str = "Chat Tester"):
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


def _create_bot(token: str, org_id: int, slug: str, **overrides) -> int:
    payload = {"name": "Bot", "slug": slug, "system_prompt": "You are helpful."}
    payload.update(overrides)
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots",
        json=payload,
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_conv(token: str, org_id: int, bot_id: int, title: str = "Conv") -> int:
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/conversations",
        json={"title": title},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _chat(token: str, org_id: int, conv_id: int, content: str = "Hello", **overrides):
    payload = {"content": content}
    payload.update(overrides)
    return client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv_id}/chat",
        json=payload,
        headers=_auth(token),
    )


def _setup() -> tuple[str, str, int, int, int]:
    email = _email(f"owner{uuid.uuid4().hex[:6]}")
    token = _login(_register(email)["email"])
    org_id = _create_org(token, "Org", _slug(f"org{uuid.uuid4().hex[:6]}"))
    bot_id = _create_bot(token, org_id, _slug(f"bot{uuid.uuid4().hex[:6]}"))
    conv_id = _create_conv(token, org_id, bot_id)
    return email, token, org_id, bot_id, conv_id


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


async def _set_provider_model(chatbot_id: int, provider_id: str, model_id: str) -> None:
    async with TestSessionLocal() as s:
        await s.execute(
            text(
                "UPDATE chatbots SET provider_id = :pid, model_id = :mid WHERE id = :cid"
            ),
            {"pid": provider_id, "mid": model_id, "cid": chatbot_id},
        )
        await s.commit()


async def _messages(conv_id: int) -> list[tuple[str, str, int, str]]:
    async with TestSessionLocal() as s:
        r = await s.execute(
            text(
                "SELECT role, content, sequence_number, COALESCE(metadata::text, '') "
                "FROM messages WHERE conversation_id = :cid ORDER BY sequence_number"
            ),
            {"cid": conv_id},
        )
        return [(role, content, seq, meta) for role, content, seq, meta in r.fetchall()]


# --- Success ---


def test_chat_succeeds_and_persists_both_messages() -> None:
    _, token, org_id, _, conv_id = _setup()
    r = _chat(token, org_id, conv_id, "Hello")
    assert r.status_code == 200
    body = r.json()
    assert body["conversation_id"] == conv_id
    assert body["user_message"]["role"] == "user"
    assert body["user_message"]["content"] == "Hello"
    assert body["user_message"]["sequence_number"] == 1
    assert body["assistant_message"]["role"] == "assistant"
    assert body["assistant_message"]["sequence_number"] == 2
    assert body["assistant_message"]["content"].startswith("[provider-a]")

    import asyncio

    rows = asyncio.run(_messages(conv_id))
    assert [(role, seq) for role, _, seq, _ in rows] == [("user", 1), ("assistant", 2)]


def test_multiple_turns_sequence() -> None:
    _, token, org_id, _, conv_id = _setup()
    _chat(token, org_id, conv_id, "one")
    _chat(token, org_id, conv_id, "two")
    import asyncio

    rows = asyncio.run(_messages(conv_id))
    assert [(role, seq) for role, _, seq, _ in rows] == [
        ("user", 1), ("assistant", 2), ("user", 3), ("assistant", 4),
    ]


def test_assistant_metadata_safe() -> None:
    _, token, org_id, bot_id, conv_id = _setup()
    r = _chat(token, org_id, conv_id, "hi")
    import asyncio

    rows = asyncio.run(_messages(conv_id))
    role, _, seq, meta = rows[1]
    assert role == "assistant"
    assert "provider_id" in meta
    assert "model_id" in meta
    assert "finish_reason" in meta
    assert "key" not in meta.lower()
    assert "secret" not in meta.lower()


def test_history_passed_and_appended() -> None:
    _, token, org_id, bot_id, conv_id = _setup()
    _chat(token, org_id, conv_id, "first")
    # Second turn response reflects only the last user message per fake provider,
    # but the DB history must contain all four messages in order.
    _chat(token, org_id, conv_id, "second")
    import asyncio

    rows = asyncio.run(_messages(conv_id))
    contents = [content for _, content, _, _ in rows]
    assert contents == ["first", "[provider-a] first", "second", "[provider-a] second"]


# --- Security ---


def test_chat_unauthenticated_401() -> None:
    _, _, org_id, _, conv_id = _setup()
    r = _chat("", org_id, conv_id, "hi")
    assert r.status_code == 401


def test_chat_wrong_organization_denied() -> None:
    _, token_a, org_a, _, conv_a = _setup()
    _, token_b, org_b, _, _ = _setup()
    # B posts to A's conversation via A's org path.
    r = _chat(token_b, org_a, conv_a, "hi")
    assert r.status_code == 403


def test_chat_cross_tenant_denied() -> None:
    _, token_a, org_a, _, conv_a = _setup()
    _, token_b, org_b, _, _ = _setup()
    # B posts A's conversation id through B's own org path — conversation is
    # not in B's org, so org-scoped lookup → 404 (denied either way).
    r = _chat(token_b, org_b, conv_a, "hi")
    assert r.status_code in (403, 404)


def test_chat_member_own_conversation_ok() -> None:
    _, owner_token, org_id, bot_id, _ = _setup()
    member_token = _setup_member(org_id, "member")
    conv_id = _create_conv(member_token, org_id, bot_id)
    r = _chat(member_token, org_id, conv_id, "hi")
    assert r.status_code == 200


def test_chat_member_other_members_conversation_denied() -> None:
    _, owner_token, org_id, bot_id, _ = _setup()
    m1 = _setup_member(org_id, "member")
    m2 = _setup_member(org_id, "member")
    conv_id = _create_conv(m1, org_id, bot_id)
    r = _chat(m2, org_id, conv_id, "hi")
    assert r.status_code == 403


def test_chat_owner_any_conversation_ok() -> None:
    _, owner_token, org_id, bot_id, _ = _setup()
    member_token = _setup_member(org_id, "member")
    conv_id = _create_conv(member_token, org_id, bot_id)
    r = _chat(owner_token, org_id, conv_id, "hi")
    assert r.status_code == 200


def test_chatbot_conversation_mismatch_denied() -> None:
    # Runtime resolves the chatbot from the conversation; a conversation under
    # one chatbot cannot be chatted with another. Verify: create conv under
    # bot A, attempt chat with path org+conv only (no chatbot in path) — the
    # conversation's own chatbot is used. Mismatch is impossible via API; the
    # guard is internal. Test that a nonexistent conversation → 404.
    _, token, org_id, _, _ = _setup()
    r = _chat(token, org_id, 999_999, "hi")
    assert r.status_code == 404


# --- Lifecycle ---


def test_chat_archived_409_no_messages() -> None:
    _, token, org_id, _, conv_id = _setup()
    _chat(token, org_id, conv_id, "first")
    r = client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv_id}/archive",
        headers=_auth(token),
    )
    assert r.status_code == 200

    r2 = _chat(token, org_id, conv_id, "second")
    assert r2.status_code == 409

    import asyncio

    rows = asyncio.run(_messages(conv_id))
    assert len(rows) == 2  # no new user message, no assistant


# --- AI errors (gateway-level, via invalid provider/model on chatbot) ---


def test_chat_unknown_provider_502_user_message_remains() -> None:
    _, token, org_id, _, conv_id = _setup()
    import asyncio

    async def _set_bad_provider() -> None:
        async with TestSessionLocal() as s:
            await s.execute(
                text(
                    "UPDATE chatbots SET provider_id = 'missing' "
                    "WHERE id = (SELECT chatbot_id FROM conversations WHERE id = :cid)"
                ),
                {"cid": conv_id},
            )
            await s.commit()

    asyncio.run(_set_bad_provider())
    r = _chat(token, org_id, conv_id, "hi")
    assert r.status_code == 502
    # User message saved, no assistant.
    rows = asyncio.run(_messages(conv_id))
    assert [(role, seq) for role, _, seq, _ in rows] == [("user", 1)]


def test_chat_unknown_model_502_no_assistant() -> None:
    _, token, org_id, _, conv_id = _setup()
    import asyncio

    async def _set_bad_model() -> None:
        async with TestSessionLocal() as s:
            await s.execute(
                text(
                    "UPDATE chatbots SET model_id = 'missing' "
                    "WHERE id = (SELECT chatbot_id FROM conversations WHERE id = :cid)"
                ),
                {"cid": conv_id},
            )
            await s.commit()

    asyncio.run(_set_bad_model())
    r = _chat(token, org_id, conv_id, "hi")
    assert r.status_code == 502
    assert "missing" not in r.text.lower()  # no provider internals leaked


def test_chat_error_response_has_no_internals() -> None:
    _, token, org_id, _, conv_id = _setup()
    import asyncio

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
    r = _chat(token, org_id, conv_id, "hi")
    assert r.status_code == 502
    assert "traceback" not in r.text.lower()
    assert "api_key" not in r.text.lower()


# --- Validation ---


def test_chat_empty_content_422() -> None:
    _, token, org_id, _, conv_id = _setup()
    assert _chat(token, org_id, conv_id, "").status_code == 422


def test_chat_whitespace_content_422() -> None:
    _, token, org_id, _, conv_id = _setup()
    assert _chat(token, org_id, conv_id, "   ").status_code == 422


def test_chat_extra_fields_422() -> None:
    _, token, org_id, _, conv_id = _setup()
    assert _chat(token, org_id, conv_id, "hi", role="assistant").status_code == 422
    assert _chat(token, org_id, conv_id, "hi", provider_id="x").status_code == 422
    assert _chat(token, org_id, conv_id, "hi", model_id="x").status_code == 422
    assert _chat(token, org_id, conv_id, "hi", sequence_number=99).status_code == 422
    assert _chat(token, org_id, conv_id, "hi", system_prompt="injected").status_code == 422
    assert _chat(token, org_id, conv_id, "hi", conversation_id=1).status_code == 422


# --- RAG runtime integration ---


class CapturingFakeProvider:
    """Fake provider that records the AIRequest it receives."""

    def __init__(self, metadata):
        self.metadata = metadata
        self.last_request = None

    async def generate(self, request):
        self.last_request = request
        from app.ai.contracts import AIResponse, AIUsage

        return AIResponse(
            content="[capture] ok",
            provider_id=request.provider_id,
            model_id=request.model_id,
            finish_reason="stop",
            usage=AIUsage(input_tokens=1, output_tokens=1),
        )


def _capture_gateway():
    """Swap gateway registries with a capturing fake provider."""
    from app.ai.capabilities import AICapability
    from app.ai.metadata import ModelMetadata, ProviderMetadata
    from app.ai.model_registry import ModelRegistry
    from app.ai.provider_registry import ProviderRegistry

    capture = CapturingFakeProvider(
        ProviderMetadata(
            provider_id="fake-a",
            display_name="A",
            description="",
            enabled=True,
            base_url="",
            authentication_type="none",
            compatibility_type="fake",
            capabilities={AICapability.TEXT_GENERATION},
        )
    )
    providers = ProviderRegistry()
    providers.register(capture)
    models = ModelRegistry()
    models.register(
        ModelMetadata(
            provider_id="fake-a",
            model_id="fake-model-small",
            display_name="s",
            context_window=1000,
            max_output_tokens=100,
            enabled=True,
            capabilities={AICapability.TEXT_GENERATION},
        )
    )
    from app.ai.registry import gateway as real_gateway

    original_providers, original_models = real_gateway.providers, real_gateway.models
    real_gateway.providers, real_gateway.models = providers, models
    return real_gateway, original_providers, original_models, capture


def _ingest_knowledge(token: str, org_id: int, bot_id: int, content: str) -> int:
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/knowledge/documents",
        json={"name": "Doc", "content": content, "source_type": "text"},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_chat_with_knowledge_reaches_ai_request() -> None:
    import asyncio

    gateway, op, om, capture = _capture_gateway()
    try:
        email = _email(f"rag{uuid.uuid4().hex[:6]}")
        token = _login(_register(email)["email"])
        org_id = _create_org(token, "Org", _slug(f"org{uuid.uuid4().hex[:6]}"))
        bot_id = _create_bot(token, org_id, _slug(f"bot{uuid.uuid4().hex[:6]}"), system_prompt="BE HELPFUL")
        _ingest_knowledge(token, org_id, bot_id, "The unicorn portal opens at midnight sharp.")
        conv_id = _create_conv(token, org_id, bot_id)
        r = _chat(token, org_id, conv_id, "When does the unicorn portal open?")
        assert r.status_code == 200
        body = r.json()
        assert body["user_message"]["content"] == "When does the unicorn portal open?"
        assert body["assistant_message"]["content"] == "[capture] ok"

        req = capture.last_request
        assert req is not None
        assert req.system_prompt == "BE HELPFUL"
        # History has: user message + knowledge context message.
        contents = [m.content for m in req.messages]
        assert any("<knowledge_context>" in c for c in contents)
        assert "unicorn portal opens at midnight" in " ".join(contents)
        # User message appears exactly once.
        assert contents.count("When does the unicorn portal open?") == 1

        # No RAG rows stored as messages.
        rows = asyncio.run(_messages(conv_id))
        assert [(role, seq) for role, _, seq, _ in rows] == [("user", 1), ("assistant", 2)]
    finally:
        gateway.providers, gateway.models = op, om


def test_chat_empty_retrieval_still_generates() -> None:
    gateway, op, om, capture = _capture_gateway()
    try:
        email = _email(f"norag{uuid.uuid4().hex[:6]}")
        token = _login(_register(email)["email"])
        org_id = _create_org(token, "Org", _slug(f"org{uuid.uuid4().hex[:6]}"))
        bot_id = _create_bot(token, org_id, _slug(f"bot{uuid.uuid4().hex[:6]}"))
        conv_id = _create_conv(token, org_id, bot_id)
        r = _chat(token, org_id, conv_id, "hello there")
        assert r.status_code == 200
        req = capture.last_request
        assert "<knowledge_context>" not in " ".join(m.content for m in req.messages)
    finally:
        gateway.providers, gateway.models = op, om


def test_chat_cross_chatbot_knowledge_blocked() -> None:
    """Chatbot A's chat never receives chatbot B's knowledge."""
    import asyncio

    gateway, op, om, capture = _capture_gateway()
    try:
        email = _email(f"iso{uuid.uuid4().hex[:6]}")
        token = _login(_register(email)["email"])
        org_id = _create_org(token, "Org", _slug(f"org{uuid.uuid4().hex[:6]}"))
        bot_a = _create_bot(token, org_id, _slug(f"bota{uuid.uuid4().hex[:6]}"))
        bot_b = _create_bot(token, org_id, _slug(f"botb{uuid.uuid4().hex[:6]}"))
        _ingest_knowledge(token, org_id, bot_b, "TOP SECRET B KNOWLEDGE")
        conv_id = _create_conv(token, org_id, bot_a)
        r = _chat(token, org_id, conv_id, "TOP SECRET B KNOWLEDGE")
        assert r.status_code == 200
        joined = " ".join(m.content for m in capture.last_request.messages)
        assert "<knowledge_context>" not in joined
        assert "TOP SECRET B KNOWLEDGE" not in joined.replace("TOP SECRET B KNOWLEDGE", "", 1)
    finally:
        gateway.providers, gateway.models = op, om


def test_chat_cross_tenant_knowledge_blocked() -> None:
    gateway, op, om, capture = _capture_gateway()
    try:
        email_a = _email(f"tena{uuid.uuid4().hex[:6]}")
        token_a = _login(_register(email_a)["email"])
        org_a = _create_org(token_a, "OrgA", _slug(f"orga{uuid.uuid4().hex[:6]}"))
        bot_a = _create_bot(token_a, org_a, _slug(f"bota{uuid.uuid4().hex[:6]}"))

        email_b = _email(f"tenb{uuid.uuid4().hex[:6]}")
        token_b = _login(_register(email_b)["email"])
        org_b = _create_org(token_b, "OrgB", _slug(f"orgb{uuid.uuid4().hex[:6]}"))
        bot_b = _create_bot(token_b, org_b, _slug(f"botb{uuid.uuid4().hex[:6]}"))
        _ingest_knowledge(token_b, org_b, bot_b, "ORGANIZATION B SECRET")

        conv_a = _create_conv(token_a, org_a, bot_a)
        r = _chat(token_a, org_a, conv_a, "ORGANIZATION B SECRET")
        assert r.status_code == 200
        joined = " ".join(m.content for m in capture.last_request.messages)
        assert "<knowledge_context>" not in joined
    finally:
        gateway.providers, gateway.models = op, om


def test_chat_client_cannot_inject_top_k() -> None:
    _, token, org_id, _, conv_id = _setup()
    assert _chat(token, org_id, conv_id, "hi", top_k=20).status_code == 422


def test_chat_with_file_knowledge_reaches_ai_request() -> None:
    """File-ingested knowledge flows into the AI request via ContextBuilder."""
    gateway, op, om, capture = _capture_gateway()
    try:
        email = _email(f"file{uuid.uuid4().hex[:6]}")
        token = _login(_register(email)["email"])
        org_id = _create_org(token, "Org", _slug(f"org{uuid.uuid4().hex[:6]}"))
        bot_id = _create_bot(token, org_id, _slug(f"bot{uuid.uuid4().hex[:6]}"))
        r = client.post(
            f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/knowledge/documents/file",
            files={"file": ("facts.txt", b"The moon cheese flavor is cheddar.")},
            headers=_auth(token),
        )
        assert r.status_code == 201, r.text
        conv_id = _create_conv(token, org_id, bot_id)
        r = _chat(token, org_id, conv_id, "What flavor is moon cheese?")
        assert r.status_code == 200
        joined = " ".join(m.content for m in capture.last_request.messages)
        assert "<knowledge_context>" in joined
        assert "moon cheese flavor is cheddar" in joined
        assert joined.count("What flavor is moon cheese?") == 1
    finally:
        gateway.providers, gateway.models = op, om


# --- Real provider through runtime (mocked HTTP) ---


def test_chat_with_mocked_openai_provider() -> None:
    """Full runtime path with a mocked OpenAI-compatible HTTP provider:
    POST /chat → ChatRuntimeService → AIGateway → adapter → mock HTTP → assistant.
    """
    import asyncio

    from httpx import AsyncClient, Response

    from app.ai.capabilities import AICapability
    from app.ai.metadata import ModelMetadata, ProviderMetadata
    from app.ai.model_registry import ModelRegistry
    from app.ai.provider_registry import ProviderRegistry
    from app.ai.providers.openai_compatible import OpenAICompatibleHTTPProvider

    class MockTransport:
        def __init__(self):
            self.requests = []

        async def handle_async_request(self, request):
            self.requests.append(request)
            return Response(
                200,
                json={
                    "choices": [{"message": {"content": "Real-ish reply"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 3},
                },
            )

    transport = MockTransport()

    def _build_gateway():
        providers = ProviderRegistry()
        models = ModelRegistry()
        providers.register(
            OpenAICompatibleHTTPProvider(
                ProviderMetadata(
                    provider_id="openai",
                    display_name="OpenAI",
                    description="mocked",
                    enabled=True,
                    base_url="https://api.mock.test/v1",
                    authentication_type="api_key",
                    compatibility_type="openai_compatible",
                    capabilities={AICapability.TEXT_GENERATION},
                ),
                api_key="sk-test-secret",
                base_url="https://api.mock.test/v1",
                timeout=30.0,
                client=AsyncClient(transport=transport),
            )
        )
        models.register(
            ModelMetadata(
                provider_id="openai",
                model_id="gpt-4o-mini",
                display_name="gpt-4o-mini",
                context_window=1000,
                max_output_tokens=100,
                enabled=True,
                capabilities={AICapability.TEXT_GENERATION},
            )
        )
        return providers, models

    from app.ai.registry import gateway as real_gateway

    original_providers, original_models = real_gateway.providers, real_gateway.models
    real_gateway.providers, real_gateway.models = _build_gateway()
    try:
        # Chatbot must reference the overridden provider/model. Registry's real
        # openai is disabled in CI, so create with fake defaults then set the
        # pair directly (validation bypassed — the overridden gateway is what
        # the runtime actually resolves).
        email = _email(f"rt{uuid.uuid4().hex[:6]}")
        token = _login(_register(email)["email"])
        org_id = _create_org(token, "Org", _slug(f"org{uuid.uuid4().hex[:6]}"))
        bot_id = _create_bot(token, org_id, _slug(f"bot{uuid.uuid4().hex[:6]}"))
        asyncio.run(
            _set_provider_model(bot_id, "openai", "gpt-4o-mini")
        )
        conv_id = _create_conv(token, org_id, bot_id)
        r = _chat(token, org_id, conv_id, "Hello")
        assert r.status_code == 200
        body = r.json()
        assert body["assistant_message"]["content"] == "Real-ish reply"
        assert body["user_message"]["sequence_number"] == 1
        assert body["assistant_message"]["sequence_number"] == 2

        # Auth header present on the mocked call, key never stored in DB.
        assert transport.requests[0].headers["Authorization"] == "Bearer sk-test-secret"
        rows = asyncio.run(_messages(conv_id))
        assert [(role, seq) for role, _, seq, _ in rows] == [("user", 1), ("assistant", 2)]
        assert all("sk-" not in meta for _, _, _, meta in rows)
    finally:
        real_gateway.providers, real_gateway.models = original_providers, original_models
