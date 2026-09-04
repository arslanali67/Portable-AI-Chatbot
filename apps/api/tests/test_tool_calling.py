"""Tool calling capture/persistence tests.

Since the tool-execution milestone, a chatbot with `tools` set (and no
`response_schema`) executes real, registered tools via
ChatRuntimeService._run_with_tool_execution() — see test_tool_execution.py
for that loop's coverage. This file covers what's unchanged: the
surface-only capture/persistence SHAPE (tool_calls -> human-readable
content summary + metadata), which still applies verbatim whenever
`response_schema` is ALSO set (the mutual-exclusion carve-out — see
architecture.md's "Tool Execution (Platform-Defined Allowlist)"), plus
the tools=NULL-unchanged and capability-gating cases which never touch
execution either way.

Uses "get_current_datetime" as the tool name throughout because chatbot
save-time validation now rejects any name not in the platform's tool
registry (app/ai/tools/registry.py) — an arbitrary name like the
original "get_weather" would be rejected at chatbot creation, before any
of these tests could even set up their scenario.

Require Docker PostgreSQL + alembic upgrade head. Run: pytest -m identity
"""

import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.ai.capabilities import AICapability
from app.ai.contracts import AIResponse, AIToolCall, AIUsage
from app.ai.metadata import ModelMetadata, ProviderMetadata
from app.ai.model_registry import ModelRegistry
from app.ai.provider_registry import ProviderRegistry
from app.main import app
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.identity

client = TestClient(app)

PASSWORD = "Strong-password-123"
_RUN = uuid.uuid4().hex[:8]

TOOLS = [
    {
        "name": "get_current_datetime",
        "description": "Get current weather for a location",
        "parameters": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
        },
    }
]

TOOL_CAPS = {AICapability.TEXT_GENERATION, AICapability.STREAMING, AICapability.TOOL_CALLING}
# The mutual-exclusion combo tests also set response_schema, which the
# gateway auto-derives an additional STRUCTURED_OUTPUT capability
# requirement from.
TOOL_AND_SCHEMA_CAPS = TOOL_CAPS | {AICapability.STRUCTURED_OUTPUT}


def _email(name: str) -> str:
    return f"{name}-{_RUN}@example.com"


def _slug(name: str) -> str:
    return f"{name}-{_RUN}"


def _register(email: str, full_name: str = "Tool Tester"):
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


def _stream(token: str, org_id: int, conv_id: int, content: str = "Hello"):
    return client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv_id}/chat/stream",
        json={"content": content},
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


def _setup(**bot_overrides) -> tuple[str, int, int, int]:
    email = _email(f"owner{uuid.uuid4().hex[:6]}")
    token = _login(_register(email)["email"])
    org_id = _create_org(token, "Org", _slug(f"org{uuid.uuid4().hex[:6]}"))
    bot_id = _create_bot(token, org_id, _slug(f"bot{uuid.uuid4().hex[:6]}"), **bot_overrides)
    conv_id = _create_conv(token, org_id, bot_id)
    return token, org_id, bot_id, conv_id


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


class ScriptedToolProvider:
    """Fake provider that always returns the same fixed AIResponse
    (with or without tool_calls) — deterministic, offline. Records every
    AIRequest it receives for call-count and request-shape assertions."""

    def __init__(self, metadata: ProviderMetadata, response: AIResponse) -> None:
        self.metadata = metadata
        self._response = response
        self.requests = []

    async def generate(self, request, credential_override=None) -> AIResponse:
        self.requests.append(request)
        return self._response

    def stream(self, request, credential_override=None):  # pragma: no cover - unused
        raise NotImplementedError("tool-calling turns always use the buffered generate() path")


def _install_provider(response: AIResponse, capabilities: set[AICapability]):
    """Swaps fake-a/fake-model-small for a scripted double, mirroring
    test_chat_runtime.py's _capture_gateway / test_structured_output.py's
    _install_scripted_provider convention."""
    provider = ScriptedToolProvider(
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
        response,
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


def _text_response(content: str) -> AIResponse:
    return AIResponse(
        content=content,
        provider_id="fake-a",
        model_id="fake-model-small",
        finish_reason="stop",
        usage=AIUsage(input_tokens=1, output_tokens=1),
    )


def _tool_call_response(content: str = "") -> AIResponse:
    return AIResponse(
        content=content,
        provider_id="fake-a",
        model_id="fake-model-small",
        finish_reason="tool_calls",
        usage=AIUsage(input_tokens=1, output_tokens=1),
        tool_calls=[
            AIToolCall(
                id="call_1", name="get_current_datetime", arguments='{"location": "Boston"}'
            )
        ],
    )


# --- tools=NULL: unchanged, exactly one call ---


def test_no_tools_makes_exactly_one_call_unchanged() -> None:
    gateway, op, om, provider = _install_provider(_text_response("plain text"), TOOL_CAPS)
    try:
        token, org_id, bot_id, conv_id = _setup()  # tools not set -> None
        r = _chat(token, org_id, conv_id, "hi")
        assert r.status_code == 200, r.text
        assert r.json()["assistant_message"]["content"] == "plain text"
        assert len(provider.requests) == 1
        assert provider.requests[0].tools is None
    finally:
        gateway.providers, gateway.models = op, om


# --- mutual exclusion: tools + response_schema together stay surface-only ---


def test_tools_and_response_schema_combo_stays_surface_only() -> None:
    """A chatbot with BOTH tools and response_schema set keeps tool calls
    surface-only/unexecuted — exact pre-milestone behavior for this
    specific combination (see architecture.md's "Tool Execution
    (Platform-Defined Allowlist)" mutual-exclusion note). The scripted
    response's content is valid JSON matching the schema so
    _generate_structured's validation passes on the first call — proving
    this is genuinely the old single-call capture path, not a retry."""
    gateway, op, om, provider = _install_provider(
        _tool_call_response(content='{"note": "ok"}'), TOOL_AND_SCHEMA_CAPS
    )
    try:
        token, org_id, bot_id, conv_id = _setup(
            tools=TOOLS, response_schema={"type": "object"}
        )
        r = _chat(token, org_id, conv_id, "what's the weather in Boston?")
        assert r.status_code == 200, r.text

        assert len(provider.requests) == 1
        assert provider.requests[0].tools == TOOLS

        body = r.json()
        assert body["assistant_message"]["content"] == (
            'Requested tool call: get_current_datetime({"location": "Boston"})'
        )

        rows = asyncio.run(_messages(conv_id))
        assert [(role, seq) for role, _, seq, _ in rows] == [("user", 1), ("assistant", 2)]
        assistant_meta = json.loads(rows[1][3])
        assert assistant_meta["tool_calls"] == [
            {
                "id": "call_1",
                "name": "get_current_datetime",
                "arguments": '{"location": "Boston"}',
            }
        ]
        assert "tool_execution_trace" not in assistant_meta
    finally:
        gateway.providers, gateway.models = op, om


# --- tools set, model responds with normal text (no tool call) ---


def test_tools_set_model_responds_with_text() -> None:
    gateway, op, om, provider = _install_provider(_text_response("It's sunny."), TOOL_CAPS)
    try:
        token, org_id, bot_id, conv_id = _setup(tools=TOOLS)
        r = _chat(token, org_id, conv_id, "hi")
        assert r.status_code == 200, r.text
        assert r.json()["assistant_message"]["content"] == "It's sunny."

        assert len(provider.requests) == 1
        rows = asyncio.run(_messages(conv_id))
        assistant_meta = json.loads(rows[1][3])
        assert "tool_calls" not in assistant_meta
    finally:
        gateway.providers, gateway.models = op, om


# --- capability gating: rejected before any gateway call ---


def test_capability_gating_rejects_before_any_call() -> None:
    gateway, op, om, provider = _install_provider(
        _text_response("should never be used"), {AICapability.TEXT_GENERATION}
    )
    try:
        token, org_id, bot_id, conv_id = _setup(tools=TOOLS)
        r = _chat(token, org_id, conv_id, "hi")
        assert r.status_code == 502, r.text
        assert len(provider.requests) == 0
    finally:
        gateway.providers, gateway.models = op, om


# --- streaming: buffered single-call path (mutual-exclusion combo) ---


def test_streaming_tools_and_response_schema_combo_uses_buffered_single_call() -> None:
    """Same mutual-exclusion carve-out as
    test_tools_and_response_schema_combo_stays_surface_only, over the
    streaming path — still exactly one buffered token+end SSE pair, no
    execution loop involved."""
    gateway, op, om, provider = _install_provider(
        _tool_call_response(content='{"note": "ok"}'), TOOL_AND_SCHEMA_CAPS
    )
    try:
        token, org_id, bot_id, conv_id = _setup(
            tools=TOOLS, response_schema={"type": "object"}
        )
        r = _stream(token, org_id, conv_id, "what's the weather?")
        assert r.status_code == 200, r.text

        assert len(provider.requests) == 1
        assert provider.requests[0].tools == TOOLS

        events = _parse_sse(r.text)
        event_types = [e for e, _ in events]
        assert event_types == ["start", "user", "start", "token", "end"]
        token_events = [data for etype, data in events if etype == "token"]
        assert token_events == [
            {"delta": 'Requested tool call: get_current_datetime({"location": "Boston"})'}
        ]

        rows = asyncio.run(_messages(conv_id))
        assert rows[1][1] == (
            'Requested tool call: get_current_datetime({"location": "Boston"})'
        )
        assistant_meta = json.loads(rows[1][3])
        assert assistant_meta["tool_calls"] == [
            {
                "id": "call_1",
                "name": "get_current_datetime",
                "arguments": '{"location": "Boston"}',
            }
        ]
        assert "tool_execution_trace" not in assistant_meta
    finally:
        gateway.providers, gateway.models = op, om
