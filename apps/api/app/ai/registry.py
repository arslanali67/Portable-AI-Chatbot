"""Default provider/model registries and gateway singleton.

Built-in fake providers for development and tests.

Real providers are registered through provider-neutral adapters.
Gemini currently uses Google's OpenAI-compatible API through
OpenAICompatibleHTTPProvider.
"""

from app.ai.capabilities import AICapability
from app.ai.gateway import AIGateway
from app.ai.metadata import ModelMetadata, ProviderMetadata
from app.ai.model_registry import ModelRegistry
from app.ai.provider_registry import ProviderRegistry
from app.ai.providers.fake import FakeAIProvider
from app.ai.providers.openai_compatible import OpenAICompatibleHTTPProvider
from app.core.config import settings


TEXT = {AICapability.TEXT_GENERATION}
TEXT_STREAM = {AICapability.TEXT_GENERATION, AICapability.STREAMING}


def build_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()

    # ============================================================
    # Fake providers
    # ============================================================

    registry.register(
        FakeAIProvider(
            ProviderMetadata(
                provider_id="fake-a",
                display_name="Fake Provider A",
                description="Deterministic offline provider A",
                enabled=True,
                base_url="",
                authentication_type="none",
                compatibility_type="fake",
                capabilities=TEXT_STREAM,
            ),
            label="provider-a",
        )
    )

    registry.register(
        FakeAIProvider(
            ProviderMetadata(
                provider_id="fake-b",
                display_name="Fake Provider B",
                description="Deterministic offline provider B",
                enabled=True,
                base_url="",
                authentication_type="none",
                compatibility_type="fake",
                capabilities=TEXT_STREAM,
            ),
            label="provider-b",
        )
    )

    # ============================================================
    # Google Gemini
    #
    # Uses Google's OpenAI-compatible API.
    # The adapter remains OpenAICompatibleHTTPProvider because
    # Gemini exposes the OpenAI-compatible /chat/completions API.
    # ============================================================

    gemini_enabled = bool(settings.openai_api_key)

    registry.register(
        OpenAICompatibleHTTPProvider(
            ProviderMetadata(
                provider_id="gemini",
                display_name="Google Gemini",
                description="Google Gemini via OpenAI-compatible API",
                enabled=gemini_enabled,
                base_url=settings.openai_base_url,
                authentication_type="api_key",
                compatibility_type="openai_compatible",
                capabilities=TEXT_STREAM,
            ),
            api_key=settings.openai_api_key or "",
            base_url=settings.openai_base_url,
            timeout=settings.openai_timeout,
        )
    )

    return registry


def build_model_registry() -> ModelRegistry:
    registry = ModelRegistry()

    # ============================================================
    # Fake models
    # ============================================================

    registry.register(
        ModelMetadata(
            provider_id="fake-a",
            model_id="fake-model-small",
            display_name="Fake Small",
            context_window=4096,
            max_output_tokens=512,
            enabled=True,
            capabilities=TEXT_STREAM,
        )
    )

    registry.register(
        ModelMetadata(
            provider_id="fake-a",
            model_id="fake-model-large",
            display_name="Fake Large",
            context_window=32768,
            max_output_tokens=4096,
            enabled=True,
            capabilities=TEXT_STREAM,
        )
    )

    registry.register(
        ModelMetadata(
            provider_id="fake-b",
            model_id="fake-model-small",
            display_name="Fake B Small",
            context_window=4096,
            max_output_tokens=512,
            enabled=True,
            capabilities=TEXT_STREAM,
        )
    )

    # ============================================================
    # Google Gemini model
    # ============================================================

    registry.register(
        ModelMetadata(
            provider_id="gemini",
            model_id=settings.openai_model,
            display_name=settings.openai_model,
            context_window=128000,
            max_output_tokens=4096,
            enabled=bool(settings.openai_api_key),
            capabilities=TEXT_STREAM,
        )
    )

    return registry


def build_gateway() -> AIGateway:
    return AIGateway(
        providers=build_provider_registry(),
        models=build_model_registry(),
    )


provider_registry = build_provider_registry()
model_registry = build_model_registry()
gateway = build_gateway()


# Chatbot defaults
DEFAULT_PROVIDER_ID = "fake-a"
DEFAULT_MODEL_ID = "fake-model-small"