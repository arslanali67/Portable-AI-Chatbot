"""Structured output tests — per-chatbot JSON-schema-validated responses.

Require Docker PostgreSQL + alembic upgrade head. Run: pytest -m identity
"""

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.ai.capabilities import AICapability
from app.ai.contracts import AIResponse, AIUsage
from app.ai.metadata import ModelMetadata, ProviderMetadata
from app.ai.model_registry import ModelRegistry
from app.ai.provider_registry import ProviderRegistry
from app.main import app
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.identity

client = TestClient(app)

PASSWORD = "Strong-password-123"
_RUN = uuid.uuid4().hex[:8]

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}

STRUCTURED_CAPS = {AICapability.TEXT_GENERATION, AICapability.STRUCTURED_OUTPUT}


def _email(name: str) -> str:
    return f"{name}-{_RUN}@example.com"


def _slug(name: str) -> str:
    return f"{name}-{_RUN}"


def _register(email: str, full_name: str = "Struct Tester"):
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
        "/api/v1/organizations", json={"name": name, "slug": slug}, headers=_auth(token)
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_bot(token: str, org_id: int, slug: str, **overrides) -> int:
    payload = {"name": "Bot", "slug": slug, "system_prompt": "You are helpful."}
    payload.update(overrides)
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots", json=payload, headers=_auth(token)
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


def _chat(token: str, org_id: int, conv_id: int, content: str = "Hello"):
    return client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv_id}/chat",
        json={"content": content},
        headers=_auth(token),
    )


def _setup(**bot_overrides) -> tuple[str, int, int, int]:
    email = _email(f"owner{uuid.uuid4().hex[:6]}")
    token = _login(_register(email)["email"])
    org_id = _create_org(token, "Org", _slug(f"org{uuid.uuid4().hex[:6]}"))
    bot_id = _create_bot(token, org_id, _slug(f"bot{uuid.uuid4().hex[:6]}"), **bot_overrides)
    conv_id = _create_conv(token, org_id, bot_id)
    return token, org_id, bot_id, conv_id


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


class ScriptedStructuredProvider:
    """Fake provider driven by a fixed script of canned responses, one per
    call, so tests can deterministically drive invalid-then-valid and
    invalid-then-invalid retry scenarios without any network. Records every
    AIRequest it receives (for call-count/feedback-content assertions) and
    every credential_override it receives (for BYOK composition assertions)."""

    def __init__(self, metadata: ProviderMetadata, responses: list[str]) -> None:
        self.metadata = metadata
        self._responses = list(responses)
        self.requests = []
        self.credential_overrides = []

    async def generate(self, request, credential_override=None) -> AIResponse:
        self.requests.append(request)
        self.credential_overrides.append(credential_override)
        index = min(len(self.requests) - 1, len(self._responses) - 1)
        content = self._responses[index]
        return AIResponse(
            content=content,
            provider_id=request.provider_id,
            model_id=request.model_id,
            finish_reason="stop",
            usage=AIUsage(input_tokens=1, output_tokens=1),
        )


def _install_scripted_provider(responses: list[str], capabilities: set[AICapability]):
    """Swaps fake-a/fake-model-small (the default chatbot provider/model)
    for a scripted double, mirroring test_chat_runtime.py's _capture_gateway
    convention. Restore gateway.providers/.models in a finally block."""
    provider = ScriptedStructuredProvider(
        ProviderMetadata(
            provider_id="fake-a",
            display_name="A",
            description="",
            enabled=True,
            base_url="",
            authentication_type="none",
            compatibility_type="fake",
            capabilities=capabilities,
        ),
        responses,
    )
    providers = ProviderRegistry()
    providers.register(provider)
    models = ModelRegistry()
    models.register(
        ModelMetadata(
            provider_id="fake-a",
            model_id="fake-model-small",
            display_name="s",
            context_window=1000,
            max_output_tokens=100,
            enabled=True,
            capabilities=capabilities,
        )
    )
    from app.ai.registry import gateway as real_gateway

    original_providers, original_models = real_gateway.providers, real_gateway.models
    real_gateway.providers, real_gateway.models = providers, models
    return real_gateway, original_providers, original_models, provider


# --- response_schema=NULL: unchanged, exactly one call ---


def test_no_schema_makes_exactly_one_call_free_text_unchanged() -> None:
    gateway, op, om, provider = _install_scripted_provider(
        ["plain free text, not JSON"], STRUCTURED_CAPS
    )
    try:
        token, org_id, bot_id, conv_id = _setup()
        r = _chat(token, org_id, conv_id, "hi")
        assert r.status_code == 200, r.text
        assert r.json()["assistant_message"]["content"] == "plain free text, not JSON"
        assert len(provider.requests) == 1
        assert provider.requests[0].response_schema is None
    finally:
        gateway.providers, gateway.models = op, om


# --- valid on first try ---


def test_valid_on_first_try_one_call_persisted() -> None:
    gateway, op, om, provider = _install_scripted_provider(
        ['{"answer": "hello"}'], STRUCTURED_CAPS
    )
    try:
        token, org_id, bot_id, conv_id = _setup(response_schema=SCHEMA)
        r = _chat(token, org_id, conv_id, "hi")
        assert r.status_code == 200, r.text
        assert r.json()["assistant_message"]["content"] == '{"answer": "hello"}'
        assert len(provider.requests) == 1
        assert provider.requests[0].response_schema == SCHEMA
    finally:
        gateway.providers, gateway.models = op, om


# --- invalid then valid: exactly one retry, feedback included, retry result persisted ---


def test_invalid_then_valid_retry_persists_corrected_result() -> None:
    gateway, op, om, provider = _install_scripted_provider(
        ['{"wrong": "field"}', '{"answer": "corrected"}'], STRUCTURED_CAPS
    )
    try:
        token, org_id, bot_id, conv_id = _setup(response_schema=SCHEMA)
        r = _chat(token, org_id, conv_id, "hi")
        assert r.status_code == 200, r.text
        assert r.json()["assistant_message"]["content"] == '{"answer": "corrected"}'

        assert len(provider.requests) == 2
        second_call_messages = provider.requests[1].messages
        joined = " ".join(m.content for m in second_call_messages)
        assert "did not satisfy the required JSON schema" in joined
        assert '{"wrong": "field"}' in joined  # the model's own invalid reply, for context

        rows = asyncio.run(_messages(conv_id))
        assert [(role, seq) for role, _, seq in rows] == [("user", 1), ("assistant", 2)]
        assert rows[1][1] == '{"answer": "corrected"}'
    finally:
        gateway.providers, gateway.models = op, om


# --- invalid on both attempts: reject clearly, persist nothing ---


def test_invalid_both_attempts_rejected_nothing_persisted() -> None:
    gateway, op, om, provider = _install_scripted_provider(
        ['{"wrong": "field"}', "still not valid json"], STRUCTURED_CAPS
    )
    try:
        token, org_id, bot_id, conv_id = _setup(response_schema=SCHEMA)
        r = _chat(token, org_id, conv_id, "hi")
        assert r.status_code == 502, r.text

        assert len(provider.requests) == 2
        rows = asyncio.run(_messages(conv_id))
        # Only the user message was persisted; no assistant message.
        assert [(role, seq) for role, _, seq in rows] == [("user", 1)]
    finally:
        gateway.providers, gateway.models = op, om


# --- capability gating: rejected before any gateway call ---


def test_capability_gating_rejects_before_any_call() -> None:
    gateway, op, om, provider = _install_scripted_provider(
        ["should never be used"], {AICapability.TEXT_GENERATION}
    )
    try:
        token, org_id, bot_id, conv_id = _setup(response_schema=SCHEMA)
        r = _chat(token, org_id, conv_id, "hi")
        assert r.status_code == 502, r.text
        assert len(provider.requests) == 0
    finally:
        gateway.providers, gateway.models = op, om


# --- BYOK + structured output composition ---


def test_byok_credential_composes_with_structured_output() -> None:
    """Closes a verification-flagged coverage gap: BYOK's credential_override
    and structured output's response_schema were previously only tested
    independently. Proves both compose correctly on the same call: the
    gateway call genuinely uses the org's BYOK credential (not the platform
    key), and the response is schema-validated and persisted correctly."""
    gateway, op, om, provider = _install_scripted_provider(
        ['{"answer": "hello"}'], STRUCTURED_CAPS
    )
    try:
        token, org_id, bot_id, conv_id = _setup(response_schema=SCHEMA)

        set_r = client.put(
            f"/api/v1/organizations/{org_id}/ai-credentials/fake-a",
            json={"api_key": "byok-secret-structured-999"},
            headers=_auth(token),
        )
        assert set_r.status_code == 200, set_r.text

        r = _chat(token, org_id, conv_id, "hi")
        assert r.status_code == 200, r.text
        assert r.json()["assistant_message"]["content"] == '{"answer": "hello"}'

        # BYOK: the gateway call genuinely used the org's credential, not the
        # platform-shared key (which would show up as None here).
        assert len(provider.credential_overrides) == 1
        assert provider.credential_overrides[0] == "byok-secret-structured-999"

        # Structured output: schema-validated on the first try, persisted —
        # same success-path assertions as test_valid_on_first_try_one_call_persisted.
        assert len(provider.requests) == 1
        assert provider.requests[0].response_schema == SCHEMA
        rows = asyncio.run(_messages(conv_id))
        assert [(role, seq) for role, _, seq in rows] == [("user", 1), ("assistant", 2)]
        assert rows[1][1] == '{"answer": "hello"}'
    finally:
        gateway.providers, gateway.models = op, om
