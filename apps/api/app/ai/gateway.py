"""AI Gateway — provider- and model-agnostic orchestration.

Validates, resolves provider/model from registries, checks enablement and
capabilities, calls the adapter, normalizes response and errors.
"""

from typing import AsyncGenerator

from app.ai.capabilities import AICapability
from app.ai.contracts import AIRequest, AIResponse
from app.ai.exceptions import (
    AIError,
    AIInvalidRequestError,
    AIModelNotFoundError,
    AIProviderError,
    AIProviderUnavailableError,
    AICapabilityNotSupportedError,
)
from app.ai.model_registry import ModelRegistry
from app.ai.provider_registry import ProviderRegistry
from app.ai.streaming import AIStreamEvent


class AIGateway:
    def __init__(self, providers: ProviderRegistry, models: ModelRegistry) -> None:
        self.providers = providers
        self.models = models

    async def generate(
        self,
        request: AIRequest,
        required_capabilities: set[AICapability] | None = None,
        credential_override: str | None = None,
    ) -> AIResponse:
        required = set(required_capabilities) if required_capabilities else {AICapability.TEXT_GENERATION}
        if request.response_schema is not None:
            required.add(AICapability.STRUCTURED_OUTPUT)
        if request.tools is not None:
            required.add(AICapability.TOOL_CALLING)
        self._validate_request(request)

        provider = self.providers.get(request.provider_id)
        if not provider.metadata.enabled:
            raise AIProviderUnavailableError(
                f"provider disabled: {request.provider_id}"
            )

        model = self.models.get(request.provider_id, request.model_id)
        if model is None:
            raise AIModelNotFoundError(
                f"unknown model {request.model_id} for provider {request.provider_id}"
            )
        if not model.enabled:
            raise AIModelNotFoundError(f"model disabled: {request.model_id}")

        missing = required - model.capabilities
        if missing:
            names = ", ".join(sorted(c.value for c in missing))
            raise AICapabilityNotSupportedError(
                f"model {request.model_id} lacks capability: {names}"
            )

        try:
            return await provider.generate(request, credential_override)
        except AIError:
            raise
        except Exception as exc:  # noqa: BLE001 - adapter boundary
            raise AIProviderError(f"provider {request.provider_id} failed: {exc}") from exc

    @staticmethod
    def _validate_request(request: AIRequest) -> None:
        if not request.provider_id.strip():
            raise AIInvalidRequestError("provider_id is required")
        if not request.model_id.strip():
            raise AIInvalidRequestError("model_id is required")
        if not request.messages:
            raise AIInvalidRequestError("at least one message is required")
        if request.max_tokens is not None and request.max_tokens <= 0:
            raise AIInvalidRequestError("max_tokens must be positive")

    def stream(
        self, request: AIRequest, credential_override: str | None = None
    ) -> AsyncGenerator[AIStreamEvent, None]:
        """Streaming variant of generate — yields normalized AIStreamEvents."""
        required = {AICapability.TEXT_GENERATION, AICapability.STREAMING}
        if request.response_schema is not None:
            required.add(AICapability.STRUCTURED_OUTPUT)
        if request.tools is not None:
            required.add(AICapability.TOOL_CALLING)
        self._validate_request(request)

        provider = self.providers.get(request.provider_id)
        if not provider.metadata.enabled:
            raise AIProviderUnavailableError(f"provider disabled: {request.provider_id}")

        model = self.models.get(request.provider_id, request.model_id)
        if model is None:
            raise AIModelNotFoundError(
                f"unknown model {request.model_id} for provider {request.provider_id}"
            )
        if not model.enabled:
            raise AIModelNotFoundError(f"model disabled: {request.model_id}")

        missing = required - model.capabilities
        if missing:
            names = ", ".join(sorted(c.value for c in missing))
            raise AICapabilityNotSupportedError(
                f"model {request.model_id} lacks capability: {names}"
            )

        return provider.stream(request, credential_override)
