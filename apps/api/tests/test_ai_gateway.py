"""AI gateway tests — registries, gateway, capabilities, errors,
multi-provider, extensibility. Pure unit tests, no DB/network required.
"""

import pytest

from app.ai.capabilities import AICapability
from app.ai.contracts import AIMessage, AIMessageRole, AIRequest
from app.ai.exceptions import (
    AICapabilityNotSupportedError,
    AIInvalidRequestError,
    AIModelNotFoundError,
    AIProviderUnavailableError,
)
from app.ai.gateway import AIGateway
from app.ai.metadata import ModelMetadata, ProviderMetadata
from app.ai.model_registry import DuplicateModelError, ModelRegistry
from app.ai.provider_registry import DuplicateProviderError, ProviderRegistry
from app.ai.providers.base import OpenAICompatibleProvider
from app.ai.providers.fake import FakeAIProvider

TEXT = {AICapability.TEXT_GENERATION}
TEXT_STREAM = {AICapability.TEXT_GENERATION, AICapability.STREAMING}


def _provider(provider_id: str, label: str, enabled: bool = True) -> FakeAIProvider:
    return FakeAIProvider(
        ProviderMetadata(
            provider_id=provider_id,
            display_name=label,
            description="test provider",
            enabled=enabled,
            base_url="",
            authentication_type="none",
            compatibility_type="fake",
            capabilities=TEXT_STREAM,
        ),
        label=label,
    )


def _model(
    provider_id: str, model_id: str, capabilities: set = TEXT_STREAM, enabled: bool = True
) -> ModelMetadata:
    return ModelMetadata(
        provider_id=provider_id,
        model_id=model_id,
        display_name=model_id,
        context_window=4096,
        max_output_tokens=512,
        enabled=enabled,
        capabilities=capabilities,
    )


def _registry_pair():
    providers = ProviderRegistry()
    models = ModelRegistry()
    providers.register(_provider("p-a", "A"))
    providers.register(_provider("p-b", "B"))
    models.register(_model("p-a", "model-1"))
    models.register(_model("p-b", "model-1"))
    return providers, models


def _request(provider_id="p-a", model_id="model-1", **kwargs) -> AIRequest:
    defaults = dict(
        messages=[AIMessage(AIMessageRole.USER, "hello")],
    )
    defaults.update(kwargs)
    return AIRequest(provider_id=provider_id, model_id=model_id, **defaults)


# --- Provider registry ---


def test_provider_register_get_list() -> None:
    registry = ProviderRegistry()
    registry.register(_provider("one", "One"))
    registry.register(_provider("two", "Two"))
    assert registry.get("one").metadata.provider_id == "one"
    assert {p.metadata.provider_id for p in registry.list()} == {"one", "two"}
    assert registry.exists("one")
    assert not registry.exists("nope")


def test_provider_unknown_raises() -> None:
    registry = ProviderRegistry()
    with pytest.raises(AIProviderUnavailableError):
        registry.get("missing")


def test_provider_duplicate_raises() -> None:
    registry = ProviderRegistry()
    registry.register(_provider("dup", "Dup"))
    with pytest.raises(DuplicateProviderError):
        registry.register(_provider("dup", "Dup Again"))


# --- Model registry ---


def test_model_register_get_list() -> None:
    registry = ModelRegistry()
    registry.register(_model("p-a", "m1"))
    registry.register(_model("p-a", "m2"))
    registry.register(_model("p-b", "m1"))
    assert registry.get("p-a", "m1") is not None
    assert registry.get("p-b", "m1") is not None
    assert {m.model_id for m in registry.list("p-a")} == {"m1", "m2"}
    assert {m.model_id for m in registry.list("p-b")} == {"m1"}
    assert registry.exists("p-a", "m2")
    assert not registry.exists("p-a", "missing")


def test_model_unknown_returns_none() -> None:
    registry = ModelRegistry()
    assert registry.get("p-a", "missing") is None


def test_model_duplicate_raises() -> None:
    registry = ModelRegistry()
    registry.register(_model("p-a", "m1"))
    with pytest.raises(DuplicateModelError):
        registry.register(_model("p-a", "m1"))


# --- Gateway ---


def test_gateway_generate_and_normalize_response() -> None:
    providers, models = _registry_pair()
    gateway = AIGateway(providers, models)
    response = pytest_run(gateway, _request())
    assert response.provider_id == "p-a"
    assert response.model_id == "model-1"
    assert response.content == "[A] hello"
    assert response.finish_reason == "stop"
    assert response.usage.total_tokens == response.usage.input_tokens + response.usage.output_tokens


def test_gateway_unknown_provider() -> None:
    providers, models = _registry_pair()
    gateway = AIGateway(providers, models)
    with pytest.raises(AIProviderUnavailableError):
        pytest_run(gateway, _request(provider_id="missing"))


def test_gateway_unknown_model() -> None:
    providers, models = _registry_pair()
    gateway = AIGateway(providers, models)
    with pytest.raises(AIModelNotFoundError):
        pytest_run(gateway, _request(model_id="missing"))


def test_gateway_disabled_provider() -> None:
    providers = ProviderRegistry()
    providers.register(_provider("off", "Off", enabled=False))
    models = ModelRegistry()
    models.register(_model("off", "m1"))
    gateway = AIGateway(providers, models)
    with pytest.raises(AIProviderUnavailableError):
        pytest_run(gateway, _request(provider_id="off"))


def test_gateway_disabled_model() -> None:
    providers, models = _registry_pair()
    models.register(_model("p-a", "off-model", enabled=False))
    gateway = AIGateway(providers, models)
    with pytest.raises(AIModelNotFoundError):
        pytest_run(gateway, _request(model_id="off-model"))


def test_gateway_model_belongs_to_provider() -> None:
    providers, models = _registry_pair()
    gateway = AIGateway(providers, models)
    # p-b has model-1; requesting p-a model-1 works, but asking p-a for a
    # model only registered on p-b must fail.
    models.register(_model("p-b", "only-b"))
    with pytest.raises(AIModelNotFoundError):
        pytest_run(gateway, _request(provider_id="p-a", model_id="only-b"))


def test_gateway_capability_failure() -> None:
    providers, models = _registry_pair()
    models.register(_model("p-a", "text-only", capabilities=TEXT))
    gateway = AIGateway(providers, models)
    with pytest.raises(AICapabilityNotSupportedError):
        pytest_run(
            gateway,
            _request(model_id="text-only"),
            required_capabilities={AICapability.STREAMING},
        )


def test_gateway_invalid_request() -> None:
    providers, models = _registry_pair()
    gateway = AIGateway(providers, models)
    with pytest.raises(AIInvalidRequestError):
        pytest_run(gateway, _request(provider_id=""))
    with pytest.raises(AIInvalidRequestError):
        pytest_run(gateway, _request(model_id=""))
    with pytest.raises(AIInvalidRequestError):
        pytest_run(gateway, AIRequest(provider_id="p-a", model_id="model-1", messages=[]))
    with pytest.raises(AIInvalidRequestError):
        pytest_run(gateway, _request(max_tokens=0))


def test_gateway_request_fields_preserved() -> None:
    providers, models = _registry_pair()
    gateway = AIGateway(providers, models)
    request = _request(
        system_prompt="be nice",
        temperature=0.3,
        max_tokens=100,
        metadata={"trace": "abc"},
        messages=[
            AIMessage(AIMessageRole.SYSTEM, "sys"),
            AIMessage(AIMessageRole.USER, "user msg"),
            AIMessage(AIMessageRole.ASSISTANT, "prev"),
        ],
    )
    response = pytest_run(gateway, request)
    assert response.content == "[A] user msg"


# --- Multi-provider proof ---


def test_multi_provider_switching_no_gateway_change() -> None:
    providers, models = _registry_pair()
    gateway = AIGateway(providers, models)
    r_a = pytest_run(gateway, _request(provider_id="p-a"))
    r_b = pytest_run(gateway, _request(provider_id="p-b"))
    assert r_a.content == "[A] hello"
    assert r_b.content == "[B] hello"
    assert r_a.provider_id != r_b.provider_id


# --- Fake provider determinism ---


def test_fake_provider_deterministic_offline() -> None:
    providers, models = _registry_pair()
    gateway = AIGateway(providers, models)
    r1 = pytest_run(gateway, _request())
    r2 = pytest_run(gateway, _request())
    assert r1.content == r2.content


def test_fake_provider_multiple_models() -> None:
    providers, models = _registry_pair()
    models.register(_model("p-a", "big-model"))
    gateway = AIGateway(providers, models)
    small = pytest_run(gateway, _request(model_id="model-1"))
    big = pytest_run(gateway, _request(model_id="big-model"))
    assert small.model_id == "model-1"
    assert big.model_id == "big-model"


# --- Extensibility: future Kimi ---


class KimiProvider(OpenAICompatibleProvider):
    async def generate(self, request: AIRequest, credential_override: str | None = None):
        last_user = next(
            (m.content for m in reversed(request.messages) if m.role.value == "user"),
            "",
        )
        from app.ai.contracts import AIResponse, AIUsage

        return AIResponse(
            content=f"[kimi-stub] {last_user}",
            provider_id=request.provider_id,
            model_id=request.model_id,
            finish_reason="stop",
            usage=AIUsage(input_tokens=5, output_tokens=2),
        )


def test_future_kimi_registration_without_core_changes() -> None:
    providers, models = _registry_pair()
    kimi = KimiProvider(
        ProviderMetadata(
            provider_id="kimi",
            display_name="Kimi",
            description="Moonshot AI (stub)",
            enabled=True,
            base_url="https://api.moonshot.ai/v1",
            authentication_type="api_key",
            compatibility_type="openai_compatible",
            capabilities=TEXT_STREAM,
        )
    )
    providers.register(kimi)
    models.register(_model("kimi", "kimi-k2-0711"))
    gateway = AIGateway(providers, models)
    response = pytest_run(gateway, _request(provider_id="kimi", model_id="kimi-k2-0711"))
    assert response.provider_id == "kimi"
    assert response.model_id == "kimi-k2-0711"
    assert "kimi" in response.content


def test_future_model_registration_only_metadata() -> None:
    providers, models = _registry_pair()
    models.register(_model("p-a", "brand-new-model"))
    gateway = AIGateway(providers, models)
    response = pytest_run(gateway, _request(model_id="brand-new-model"))
    assert response.model_id == "brand-new-model"


# --- Helper ---


def pytest_run(gateway: AIGateway, request: AIRequest, **kwargs):
    import asyncio

    return asyncio.run(gateway.generate(request, **kwargs))
