"""Real OpenAI-compatible provider tests.

All HTTP is mocked — no network, no API key required. Verifies request
conversion, response normalization, error mapping, and security boundaries.
"""

import pytest
from httpx import AsyncClient, Request, Response

from app.ai.contracts import AIMessage, AIMessageRole, AIRequest
from app.ai.exceptions import (
    AIAuthenticationError,
    AIInvalidRequestError,
    AIModelNotFoundError,
    AIProviderError,
    AIProviderUnavailableError,
    AIRateLimitError,
)
from app.ai.metadata import ProviderMetadata
from app.ai.providers.openai_compatible import OpenAICompatibleHTTPProvider
from app.ai.capabilities import AICapability


def _provider(client) -> OpenAICompatibleHTTPProvider:
    return OpenAICompatibleHTTPProvider(
        ProviderMetadata(
            provider_id="openai",
            display_name="OpenAI",
            description="test",
            enabled=True,
            base_url="https://api.example.com/v1",
            authentication_type="api_key",
            compatibility_type="openai_compatible",
            capabilities={AICapability.TEXT_GENERATION},
        ),
        api_key="sk-test-secret-123",
        base_url="https://api.example.com/v1",
        timeout=30.0,
        client=client,
    )


def _request(**kwargs) -> AIRequest:
    defaults = dict(
        provider_id="openai",
        model_id="gpt-4o-mini",
        system_prompt="You are helpful.",
        temperature=0.5,
        max_tokens=100,
        messages=[
            AIMessage(AIMessageRole.USER, "Hello"),
            AIMessage(AIMessageRole.ASSISTANT, "Hi there"),
        ],
    )
    defaults.update(kwargs)
    return AIRequest(**defaults)


class MockTransport:
    def __init__(self, response: Response | None = None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.requests: list[Request] = []

    async def handle_async_request(self, request: Request) -> Response:
        self.requests.append(request)
        if self._error:
            raise self._error
        return self._response


def _ok_response():
    return Response(
        200,
        json={
            "choices": [
                {"message": {"content": "Mock reply"}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 15, "completion_tokens": 5},
        },
    )


def _transport(response=None, error=None):
    return MockTransport(response or _ok_response(), error)


async def _generate(transport) -> tuple:
    provider = _provider(AsyncClient(transport=transport))
    response = await provider.generate(_request())
    return provider, response


# --- Request conversion ---


@pytest.mark.asyncio
async def test_url_and_auth_header() -> None:
    t = _transport()
    provider = _provider(AsyncClient(transport=t))
    await provider.generate(_request())
    req = t.requests[0]
    assert str(req.url) == "https://api.example.com/v1/chat/completions"
    assert req.headers["Authorization"] == "Bearer sk-test-secret-123"


@pytest.mark.asyncio
async def test_payload_model_messages_and_system_prompt() -> None:
    t = _transport()
    provider = _provider(AsyncClient(transport=t))
    await provider.generate(_request())
    body = t.requests[0].content  # httpx MockTransport stores raw bytes
    import json

    payload = json.loads(body)
    assert payload["model"] == "gpt-4o-mini"
    assert payload["temperature"] == 0.5
    assert payload["max_tokens"] == 100
    assert payload["messages"][0] == {"role": "system", "content": "You are helpful."}
    assert payload["messages"][1] == {"role": "user", "content": "Hello"}
    assert payload["messages"][2] == {"role": "assistant", "content": "Hi there"}
    assert "metadata" not in payload


@pytest.mark.asyncio
async def test_no_system_prompt_when_none() -> None:
    t = _transport()
    provider = _provider(AsyncClient(transport=t))
    await provider.generate(_request(system_prompt=None))
    import json

    payload = json.loads(t.requests[0].content)
    assert all(m["role"] != "system" for m in payload["messages"])


@pytest.mark.asyncio
async def test_payload_omits_tools_when_absent() -> None:
    t = _transport()
    provider = _provider(AsyncClient(transport=t))
    await provider.generate(_request())
    import json

    payload = json.loads(t.requests[0].content)
    assert "tools" not in payload


@pytest.mark.asyncio
async def test_payload_wraps_tools_in_openai_function_shape_when_present() -> None:
    t = _transport()
    provider = _provider(AsyncClient(transport=t))
    tools = [
        {
            "name": "get_weather",
            "description": "Get current weather",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        }
    ]
    await provider.generate(_request(tools=tools))
    import json

    payload = json.loads(t.requests[0].content)
    assert payload["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get current weather",
                "parameters": {
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                    "required": ["location"],
                },
            },
        }
    ]


# --- Response normalization ---


@pytest.mark.asyncio
async def test_response_parsing() -> None:
    _, response = await _generate(_transport())
    assert response.content == "Mock reply"
    assert response.provider_id == "openai"
    assert response.model_id == "gpt-4o-mini"
    assert response.finish_reason == "stop"
    assert response.usage.input_tokens == 15
    assert response.usage.output_tokens == 5
    assert response.usage.total_tokens == 20
    assert response.tool_calls is None


@pytest.mark.asyncio
async def test_missing_content_defaults_empty() -> None:
    t = _transport(
        Response(
            200,
            json={"choices": [{"message": {}, "finish_reason": "stop"}], "usage": {}},
        )
    )
    _, response = await _generate(t)
    assert response.content == ""
    assert response.usage.total_tokens == 0


@pytest.mark.asyncio
async def test_tool_calls_extracted_from_response() -> None:
    """Closes the exact latent gap flagged during the structured-output
    milestone: a real tool_calls-bearing response is no longer silently
    dropped into an empty-content message."""
    t = _transport(
        Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_abc123",
                                    "type": "function",
                                    "function": {
                                        "name": "get_weather",
                                        "arguments": '{"location": "Boston"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
        )
    )
    _, response = await _generate(t)
    assert response.content == ""
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls is not None
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.id == "call_abc123"
    assert call.name == "get_weather"
    assert call.arguments == '{"location": "Boston"}'  # raw string, not parsed


@pytest.mark.asyncio
async def test_no_tool_calls_key_leaves_tool_calls_none() -> None:
    t = _transport(_ok_response())
    _, response = await _generate(t)
    assert response.tool_calls is None


# --- Error mapping ---


@pytest.mark.asyncio
async def test_400_maps_invalid_request() -> None:
    t = _transport(Response(400, json={"error": "bad"}))
    with pytest.raises(AIInvalidRequestError):
        await _generate(t)


@pytest.mark.asyncio
async def test_401_maps_auth_error() -> None:
    t = _transport(Response(401, json={}))
    with pytest.raises(AIAuthenticationError):
        await _generate(t)


@pytest.mark.asyncio
async def test_403_maps_auth_error() -> None:
    t = _transport(Response(403, json={}))
    with pytest.raises(AIAuthenticationError):
        await _generate(t)


@pytest.mark.asyncio
async def test_404_maps_model_not_found() -> None:
    t = _transport(Response(404, json={}))
    with pytest.raises(AIModelNotFoundError):
        await _generate(t)


@pytest.mark.asyncio
async def test_429_maps_rate_limit() -> None:
    t = _transport(Response(429, json={}))
    with pytest.raises(AIRateLimitError):
        await _generate(t)


@pytest.mark.asyncio
async def test_500_maps_provider_error() -> None:
    t = _transport(Response(500, json={}))
    with pytest.raises(AIProviderError):
        await _generate(t)


@pytest.mark.asyncio
async def test_502_503_504_map_unavailable() -> None:
    for status in (502, 503, 504):
        t = _transport(Response(status, json={}))
        with pytest.raises(AIProviderUnavailableError):
            await _generate(t)


@pytest.mark.asyncio
async def test_timeout_maps_unavailable() -> None:
    import httpx

    t = _transport(error=httpx.ConnectTimeout("timeout"))
    with pytest.raises(AIProviderUnavailableError):
        await _generate(t)


@pytest.mark.asyncio
async def test_malformed_response_maps_provider_error() -> None:
    t = _transport(Response(200, json={"unexpected": True}))
    with pytest.raises(AIProviderError):
        await _generate(t)


# --- Security: no secrets in exceptions/responses ---


@pytest.mark.asyncio
async def test_api_key_absent_from_exception() -> None:
    t = _transport(Response(401, json={}))
    with pytest.raises(AIAuthenticationError) as exc_info:
        await _generate(t)
    assert "sk-test-secret-123" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_api_key_absent_from_response() -> None:
    _, response = await _generate(_transport())
    dumped = str(response.__dict__)
    assert "sk-test-secret-123" not in dumped
    assert "sk-" not in dumped


@pytest.mark.asyncio
async def test_raw_provider_response_does_not_escape() -> None:
    t = _transport(
        Response(
            200,
            json={"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}], "usage": {}},
        )
    )
    _, response = await _generate(t)
    # Response carries only normalized fields.
    assert set(response.__dict__) == {
        "content",
        "provider_id",
        "model_id",
        "finish_reason",
        "usage",
        "metadata",
        "tool_calls",
    }


# --- Gemini via OpenAI-compatible adapter ---


def _gemini_provider(client) -> OpenAICompatibleHTTPProvider:
    """Google Gemini configured through the shared OpenAI-compatible adapter."""
    return OpenAICompatibleHTTPProvider(
        ProviderMetadata(
            provider_id="gemini",
            display_name="Google Gemini",
            description="Gemini via OpenAI-compatible API",
            enabled=True,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            authentication_type="api_key",
            compatibility_type="openai_compatible",
            capabilities={AICapability.TEXT_GENERATION, AICapability.STREAMING},
        ),
        api_key="test-gemini-key",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        timeout=30.0,
        client=client,
    )


@pytest.mark.asyncio
async def test_gemini_openai_compatible_endpoint_and_payload() -> None:
    t = _transport()
    provider = _gemini_provider(AsyncClient(transport=t))
    await provider.generate(_request(provider_id="gemini", model_id="gemini-3.6-flash"))
    req = t.requests[0]
    # Adapter appends /chat/completions to the Gemini OpenAI-compatible base.
    assert (
        str(req.url)
        == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )
    assert req.headers["Authorization"] == "Bearer test-gemini-key"
    import json

    payload = json.loads(req.content)
    assert payload["model"] == "gemini-3.6-flash"
    assert payload["messages"][0] == {"role": "system", "content": "You are helpful."}
    assert payload["messages"][1] == {"role": "user", "content": "Hello"}
    assert payload["temperature"] == 0.5
    assert payload["max_tokens"] == 100
    assert "metadata" not in payload


@pytest.mark.asyncio
async def test_gemini_openai_compatible_response_parsing() -> None:
    provider = _gemini_provider(AsyncClient(transport=_transport()))
    response = await provider.generate(
        _request(provider_id="gemini", model_id="gemini-3.6-flash")
    )
    assert response.content == "Mock reply"
    assert response.provider_id == "gemini"
    assert response.model_id == "gemini-3.6-flash"
    assert response.usage.total_tokens == 20
    assert "test-gemini-key" not in str(response.__dict__)


@pytest.mark.asyncio
async def test_gemini_openai_compatible_streaming_parsing() -> None:
    body = "\n\n".join(
        [
            'data: {"choices":[{"delta":{"content":"Hel"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{"content":"lo"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":2}}',
            "data: [DONE]",
        ]
    )
    t = MockTransport(Response(200, content=body))
    provider = _gemini_provider(AsyncClient(transport=t))
    request = _request(provider_id="gemini", model_id="gemini-3.6-flash")
    events = [event async for event in provider.stream(request)]
    assert [e.type.value for e in events] == ["start", "token", "token", "end"]
    tokens = [e.data["delta"] for e in events if e.type.value == "token"]
    assert tokens == ["Hel", "lo"]
    end = events[-1]
    assert end.data["finish_reason"] == "stop"
    assert end.data["usage"] == {"input_tokens": 3, "output_tokens": 2}


# --- Gateway integration ---


@pytest.mark.asyncio
async def test_gateway_resolves_openai_provider() -> None:
    from app.ai.gateway import AIGateway
    from app.ai.metadata import ModelMetadata
    from app.ai.model_registry import ModelRegistry
    from app.ai.provider_registry import ProviderRegistry

    providers = ProviderRegistry()
    models = ModelRegistry()
    providers.register(_provider(AsyncClient(transport=_transport())))
    models.register(
        ModelMetadata(
            provider_id="openai",
            model_id="gpt-4o-mini",
            display_name="m",
            context_window=1000,
            max_output_tokens=100,
            enabled=True,
            capabilities={AICapability.TEXT_GENERATION},
        )
    )
    gateway = AIGateway(providers, models)
    response = await gateway.generate(_request())
    assert response.content == "Mock reply"
    assert response.provider_id == "openai"


@pytest.mark.asyncio
async def test_gateway_fake_provider_still_works() -> None:
    from app.ai.gateway import AIGateway
    from app.ai.metadata import ModelMetadata
    from app.ai.model_registry import ModelRegistry
    from app.ai.provider_registry import ProviderRegistry
    from app.ai.providers.fake import FakeAIProvider

    providers = ProviderRegistry()
    providers.register(
        FakeAIProvider(
            ProviderMetadata(
                provider_id="fake-a",
                display_name="A",
                description="",
                enabled=True,
                base_url="",
                authentication_type="none",
                compatibility_type="fake",
                capabilities={AICapability.TEXT_GENERATION},
            ),
            label="provider-a",
        )
    )
    models = ModelRegistry()
    models.register(
        ModelMetadata(
            provider_id="fake-a",
            model_id="fake-model-small",
            display_name="s",
            context_window=100,
            max_output_tokens=10,
            enabled=True,
            capabilities={AICapability.TEXT_GENERATION},
        )
    )
    gateway = AIGateway(providers, models)
    response = await gateway.generate(
        AIRequest(
            provider_id="fake-a",
            model_id="fake-model-small",
            messages=[AIMessage(AIMessageRole.USER, "hello")],
        )
    )
    assert response.content == "[provider-a] hello"
