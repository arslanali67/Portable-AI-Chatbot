"""Tool execution loop — integration tests through the real HTTP/DB stack.

Covers ChatRuntimeService._run_with_tool_execution(): the full multi-turn
loop, the 5-iteration cap and forced-final-answer mechanism, tool
execution failure/timeout handling, chatbots.tools save-time validation,
cross-tenant safety for search_knowledge_base, and streaming behavior.
See test_tool_execution.py for the 3 tools' individual unit-level
behavior (no DB required there).

Require Docker PostgreSQL + alembic upgrade head. Run: pytest -m identity
"""

import asyncio
import contextlib
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.ai.capabilities import AICapability
from app.ai.contracts import AIResponse, AIToolCall, AIUsage
from app.ai.metadata import ModelMetadata, ProviderMetadata
from app.ai.model_registry import ModelRegistry
from app.ai.provider_registry import ProviderRegistry
from app.ai.registry import tool_registry
from app.core.config import settings
from app.main import app
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.identity

client = TestClient(app)

PASSWORD = "Strong-password-123"
_RUN = uuid.uuid4().hex[:8]

TOOLS = [{"name": "calculate", "description": "d", "parameters": {"type": "object"}}]
CAPS = {AICapability.TEXT_GENERATION, AICapability.STREAMING, AICapability.TOOL_CALLING}


def _email(name: str) -> str:
    return f"{name}-{_RUN}@example.com"


def _slug(name: str) -> str:
    return f"{name}-{_RUN}"


def _register(email: str, full_name: str = "Tester"):
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


def _create_bot_raw(token: str, org_id: int, slug: str, **overrides):
    payload = {"name": "Bot", "slug": slug, "system_prompt": "You are helpful."}
    payload.update(overrides)
    return client.post(
        f"/api/v1/organizations/{org_id}/chatbots", json=payload, headers=_auth(token)
    )


def _create_bot(token: str, org_id: int, slug: str, **overrides) -> int:
    r = _create_bot_raw(token, org_id, slug, **overrides)
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


def _ingest(token: str, org_id: int, bot_id: int, content: str, name: str = "Doc"):
    return client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/knowledge/documents",
        json={"name": name, "content": content, "source_type": "text"},
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


def _text_response(content: str) -> AIResponse:
    return AIResponse(
        content=content,
        provider_id="fake-a",
        model_id="fake-model-small",
        finish_reason="stop",
        usage=AIUsage(input_tokens=1, output_tokens=1),
    )


def _tool_call_response(name: str, arguments: str, call_id: str = "call_1") -> AIResponse:
    return AIResponse(
        content="",
        provider_id="fake-a",
        model_id="fake-model-small",
        finish_reason="tool_calls",
        usage=AIUsage(input_tokens=1, output_tokens=1),
        tool_calls=[AIToolCall(id=call_id, name=name, arguments=arguments)],
    )


class SequencedToolProvider:
    """Returns one scripted response per call, in order; repeats the last
    one if called more times than there are scripted responses. Records
    every AIRequest received for call-count and request-shape assertions."""

    def __init__(self, metadata: ProviderMetadata, responses: list[AIResponse]) -> None:
        self.metadata = metadata
        self._responses = responses
        self.requests: list = []

    async def generate(self, request, credential_override=None) -> AIResponse:
        self.requests.append(request)
        idx = min(len(self.requests) - 1, len(self._responses) - 1)
        return self._responses[idx]

    def stream(self, request, credential_override=None):  # pragma: no cover - unused
        raise NotImplementedError("tool-calling turns always use the buffered generate() path")


class ToolAwareLoopingProvider:
    """Always requests a tool call while `tools` is offered on the
    request, and only returns final text once tools are omitted —
    models a well-behaved model reacting to the forced-final-iteration
    mechanism (tools omitted -> model stops requesting tools)."""

    def __init__(self, metadata: ProviderMetadata) -> None:
        self.metadata = metadata
        self.requests: list = []

    async def generate(self, request, credential_override=None) -> AIResponse:
        self.requests.append(request)
        call_number = len(self.requests)
        if request.tools:
            return _tool_call_response(
                "calculate", '{"expression": "1+1"}', call_id=f"call_{call_number}"
            )
        return _text_response("Final answer after cap.")

    def stream(self, request, credential_override=None):  # pragma: no cover - unused
        raise NotImplementedError("tool-calling turns always use the buffered generate() path")


def _install_provider(provider):
    """Swaps fake-a/fake-model-small for a scripted double, mirroring
    test_tool_calling.py's convention."""
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
            capabilities=CAPS,
        )
    )
    from app.ai.registry import gateway as real_gateway

    original_providers, original_models = real_gateway.providers, real_gateway.models
    real_gateway.providers, real_gateway.models = providers, models
    return real_gateway, original_providers, original_models


def _scripted_provider(responses):
    return SequencedToolProvider(
        ProviderMetadata(
            provider_id="fake-a",
            display_name="A",
            description="",
            enabled=True,
            base_url="",
            authentication_type="none",
            compatibility_type="fake",
            capabilities=CAPS,
        ),
        responses,
    )


def _looping_provider():
    return ToolAwareLoopingProvider(
        ProviderMetadata(
            provider_id="fake-a",
            display_name="A",
            description="",
            enabled=True,
            base_url="",
            authentication_type="none",
            compatibility_type="fake",
            capabilities=CAPS,
        )
    )


class _BrokenTool:
    name = "calculate"
    description = "test double that always raises unexpectedly"
    parameters_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments, *, organization_id, chatbot_id, db_session):
        raise RuntimeError("simulated unexpected internal failure detail")


class _SlowTool:
    name = "calculate"
    description = "test double that hangs"
    parameters_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments, *, organization_id, chatbot_id, db_session):
        await asyncio.sleep(2.0)
        return "should never be reached"


@contextlib.contextmanager
def _swap_tool(name: str, tool: object):
    """Temporarily replaces a registered tool with a test double, mirroring
    this file's/test_tool_calling.py's established provider-swap pattern —
    a direct, test-only reach into the registry's internal state."""
    original = tool_registry._tools.get(name)
    tool_registry._tools[name] = tool
    try:
        yield
    finally:
        if original is not None:
            tool_registry._tools[name] = original
        else:
            del tool_registry._tools[name]


@contextlib.contextmanager
def _patch_tool_timeout(seconds: float):
    original = settings.tool_execution_timeout_seconds
    settings.tool_execution_timeout_seconds = seconds
    try:
        yield
    finally:
        settings.tool_execution_timeout_seconds = original


# --- chatbots.tools save-time validation ---


def test_unregistered_tool_name_rejected_at_creation() -> None:
    email = _email(f"owner{uuid.uuid4().hex[:6]}")
    token = _login(_register(email)["email"])
    org_id = _create_org(token, "Org", _slug(f"org{uuid.uuid4().hex[:6]}"))
    r = _create_bot_raw(
        token,
        org_id,
        _slug(f"bot{uuid.uuid4().hex[:6]}"),
        tools=[{"name": "not_a_real_tool", "description": "d", "parameters": {}}],
    )
    assert r.status_code == 422, r.text


def test_registered_tool_name_accepted_at_creation() -> None:
    email = _email(f"owner{uuid.uuid4().hex[:6]}")
    token = _login(_register(email)["email"])
    org_id = _create_org(token, "Org", _slug(f"org{uuid.uuid4().hex[:6]}"))
    r = _create_bot_raw(token, org_id, _slug(f"bot{uuid.uuid4().hex[:6]}"), tools=TOOLS)
    assert r.status_code == 201, r.text


# --- full loop: tool requested, executed, model returns final text ---


def test_full_loop_two_calls_one_persisted_message_with_trace() -> None:
    provider = _scripted_provider(
        [
            _tool_call_response("calculate", '{"expression": "2+2"}'),
            _text_response("The answer is 4."),
        ]
    )
    gateway, op, om = _install_provider(provider)
    try:
        token, org_id, bot_id, conv_id = _setup(tools=TOOLS)
        r = _chat(token, org_id, conv_id, "what is 2+2?")
        assert r.status_code == 200, r.text
        assert r.json()["assistant_message"]["content"] == "The answer is 4."

        assert len(provider.requests) == 2
        # The second (follow-up) call replayed the tool exchange correctly.
        second_call_messages = provider.requests[1].messages
        assistant_tool_msg = next(m for m in second_call_messages if m.tool_calls)
        assert assistant_tool_msg.tool_calls[0].id == "call_1"
        tool_result_msg = next(m for m in second_call_messages if m.tool_call_id == "call_1")
        assert tool_result_msg.content == "4"

        # Only user + final assistant message persisted — no intermediate rows.
        rows = asyncio.run(_messages(conv_id))
        assert [(role, seq) for role, _, seq, _ in rows] == [("user", 1), ("assistant", 2)]
        assert rows[1][1] == "The answer is 4."
        assistant_meta = json.loads(rows[1][3])
        assert "tool_calls" not in assistant_meta
        assert assistant_meta["tool_execution_trace"] == [
            {
                "iteration": 1,
                "name": "calculate",
                "arguments": '{"expression": "2+2"}',
                "result": "4",
            }
        ]
    finally:
        gateway.providers, gateway.models = op, om


# --- cap exhaustion ---


def test_cap_exhaustion_forces_final_answer_without_tools() -> None:
    provider = _looping_provider()
    gateway, op, om = _install_provider(provider)
    try:
        token, org_id, bot_id, conv_id = _setup(tools=TOOLS)
        r = _chat(token, org_id, conv_id, "keep calculating forever")
        assert r.status_code == 200, r.text

        assert len(provider.requests) == 5
        # Structural proof, not an assumption: the 5th (final) request had
        # tools omitted entirely, while the first 4 had them attached.
        for i in range(4):
            assert provider.requests[i].tools == TOOLS
        assert provider.requests[4].tools is None

        body = r.json()
        assert body["assistant_message"]["content"] == "Final answer after cap."

        rows = asyncio.run(_messages(conv_id))
        assert [(role, seq) for role, _, seq, _ in rows] == [("user", 1), ("assistant", 2)]
        assistant_meta = json.loads(rows[1][3])
        assert len(assistant_meta["tool_execution_trace"]) == 4
        assert [e["iteration"] for e in assistant_meta["tool_execution_trace"]] == [1, 2, 3, 4]
    finally:
        gateway.providers, gateway.models = op, om


# --- tool execution failure ---


def test_tool_execution_failure_fed_back_cleanly_turn_completes(caplog) -> None:
    provider = _scripted_provider(
        [
            _tool_call_response("calculate", '{"expression": "1+1"}'),
            _text_response("Done despite tool failure."),
        ]
    )
    gateway, op, om = _install_provider(provider)
    try:
        token, org_id, bot_id, conv_id = _setup(tools=TOOLS)
        with _swap_tool("calculate", _BrokenTool()):
            r = _chat(token, org_id, conv_id, "calculate 1+1")
        assert r.status_code == 200, r.text
        assert r.json()["assistant_message"]["content"] == "Done despite tool failure."
        assert len(provider.requests) == 2

        # The error result fed back to the model is clean/generic — never
        # the raw exception message.
        second_call_messages = provider.requests[1].messages
        tool_result_msg = next(m for m in second_call_messages if m.tool_call_id == "call_1")
        assert "simulated unexpected internal failure detail" not in tool_result_msg.content
        error_payload = json.loads(tool_result_msg.content)
        assert error_payload == {"error": "tool execution failed"}

        rows = asyncio.run(_messages(conv_id))
        assistant_meta = json.loads(rows[1][3])
        trace_result = assistant_meta["tool_execution_trace"][0]["result"]
        assert "simulated unexpected internal failure detail" not in trace_result

        # Never a raw traceback/exception message anywhere in captured logs.
        assert "simulated unexpected internal failure detail" not in caplog.text
    finally:
        gateway.providers, gateway.models = op, om


# --- tool execution timeout ---


def test_tool_execution_timeout_uses_configured_value_not_hardcoded() -> None:
    provider = _scripted_provider(
        [
            _tool_call_response("calculate", '{"expression": "1+1"}'),
            _text_response("Done despite timeout."),
        ]
    )
    gateway, op, om = _install_provider(provider)
    try:
        token, org_id, bot_id, conv_id = _setup(tools=TOOLS)
        with _swap_tool("calculate", _SlowTool()), _patch_tool_timeout(0.1):
            start = time.monotonic()
            r = _chat(token, org_id, conv_id, "calculate 1+1")
            elapsed = time.monotonic() - start
        assert r.status_code == 200, r.text
        # The slow tool sleeps 2.0s; if the hardcoded 5.0s default were
        # used instead of the patched 0.1s setting, this would take ~2.0s
        # (bounded by the tool's own sleep). Finishing well under 1s proves
        # the configured value was actually read, not a hardcoded number.
        assert elapsed < 1.0, f"took {elapsed}s — timeout setting was not honored"

        assert r.json()["assistant_message"]["content"] == "Done despite timeout."
        second_call_messages = provider.requests[1].messages
        tool_result_msg = next(m for m in second_call_messages if m.tool_call_id == "call_1")
        assert json.loads(tool_result_msg.content) == {"error": "tool execution timed out"}
    finally:
        gateway.providers, gateway.models = op, om


# --- streaming: buffered branch stays one token+end pair regardless of loop length ---


def test_streaming_full_loop_still_one_buffered_token_end_pair() -> None:
    provider = _scripted_provider(
        [
            _tool_call_response("calculate", '{"expression": "2+2"}'),
            _text_response("The answer is 4."),
        ]
    )
    gateway, op, om = _install_provider(provider)
    try:
        token, org_id, bot_id, conv_id = _setup(tools=TOOLS)
        r = _stream(token, org_id, conv_id, "what is 2+2?")
        assert r.status_code == 200, r.text

        assert len(provider.requests) == 2  # internal loop ran twice

        events = _parse_sse(r.text)
        event_types = [e for e, _ in events]
        assert event_types == ["start", "user", "start", "token", "end"]
        token_events = [data for etype, data in events if etype == "token"]
        assert token_events == [{"delta": "The answer is 4."}]

        rows = asyncio.run(_messages(conv_id))
        assert rows[1][1] == "The answer is 4."
        assistant_meta = json.loads(rows[1][3])
        assert assistant_meta["tool_execution_trace"] == [
            {
                "iteration": 1,
                "name": "calculate",
                "arguments": '{"expression": "2+2"}',
                "result": "4",
            }
        ]
    finally:
        gateway.providers, gateway.models = op, om


# --- search_knowledge_base: cross-tenant structural proof ---


def test_knowledge_search_tool_ignores_tenant_ids_in_model_supplied_arguments() -> None:
    """The model-supplied tool-call arguments can only ever be 'query' and
    'top_k' per the tool's own parameters_schema — but even if a
    malicious/confused model's arguments dict smuggled organization_id/
    chatbot_id keys, the tool must never read them: only the platform-
    supplied keyword-only organization_id/chatbot_id (never derived from
    arguments) determine which tenant is queried."""
    owner_a_email = _email(f"ownera{uuid.uuid4().hex[:6]}")
    token_a = _login(_register(owner_a_email)["email"])
    org_a = _create_org(token_a, "Org A", _slug(f"orga{uuid.uuid4().hex[:6]}"))
    bot_a = _create_bot(token_a, org_a, _slug(f"bota{uuid.uuid4().hex[:6]}"))
    assert _ingest(token_a, org_a, bot_a, content="ORG_A_SECRET_MARKER content here").status_code == 201

    owner_b_email = _email(f"ownerb{uuid.uuid4().hex[:6]}")
    token_b = _login(_register(owner_b_email)["email"])
    org_b = _create_org(token_b, "Org B", _slug(f"orgb{uuid.uuid4().hex[:6]}"))
    bot_b = _create_bot(token_b, org_b, _slug(f"botb{uuid.uuid4().hex[:6]}"))
    assert _ingest(token_b, org_b, bot_b, content="ORG_B_SECRET_MARKER content here").status_code == 201

    from app.ai.tools.knowledge_search_tool import KnowledgeSearchTool

    async def _run_search():
        async with TestSessionLocal() as session:
            tool = KnowledgeSearchTool()
            # Malicious/confused arguments attempt to point at org B — the
            # tool's execute() signature only ever reads "query"/"top_k"
            # from this dict; organization_id/chatbot_id below (org_a/
            # bot_a) are the only ones that can possibly take effect.
            return await tool.execute(
                {
                    "query": "SECRET_MARKER",
                    "organization_id": org_b,
                    "chatbot_id": bot_b,
                },
                organization_id=org_a,
                chatbot_id=bot_a,
                db_session=session,
            )

    result = asyncio.run(_run_search())
    assert "ORG_A_SECRET_MARKER" in result
    assert "ORG_B_SECRET_MARKER" not in result


def test_knowledge_search_tool_no_results_clean_message() -> None:
    email = _email(f"owner{uuid.uuid4().hex[:6]}")
    token = _login(_register(email)["email"])
    org_id = _create_org(token, "Org", _slug(f"org{uuid.uuid4().hex[:6]}"))
    bot_id = _create_bot(token, org_id, _slug(f"bot{uuid.uuid4().hex[:6]}"))

    from app.ai.tools.knowledge_search_tool import KnowledgeSearchTool

    async def _run_search():
        async with TestSessionLocal() as session:
            return await KnowledgeSearchTool().execute(
                {"query": "anything, no documents ever ingested"},
                organization_id=org_id,
                chatbot_id=bot_id,
                db_session=session,
            )

    result = asyncio.run(_run_search())
    assert result == "No relevant results found in the knowledge base."
