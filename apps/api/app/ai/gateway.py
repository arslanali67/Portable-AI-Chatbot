"""AI Gateway — provider- and model-agnostic orchestration.

Validates, resolves provider/model from registries, checks enablement and
capabilities, calls the adapter, normalizes response and errors. Also owns
transient-failure retry-with-backoff — see architecture.md's "Transient
Provider Error Retry" section (§13) for the full design rationale.
"""

import asyncio
import random
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
from app.core.logging import get_logger

logger = get_logger("portableai.ai_gateway")

# Retry only AIProviderUnavailableError (408/502/503/504, timeouts) — every
# other exception type (auth, invalid request, model not found, capability,
# rate limit, generic provider error) propagates on first occurrence,
# unchanged. 3 total attempts (1 original + 2 retries), exponential backoff
# with jitter: 300ms before retry 1, 600ms before retry 2, capped at 2s.
_MAX_ATTEMPTS = 3
_BASE_DELAY_SECONDS = 0.3
_BACKOFF_FACTOR = 2
_MAX_DELAY_SECONDS = 2.0
_JITTER_SECONDS = 0.1


def _backoff_delay(retry_number: int) -> float:
    """Delay before the given retry (1 = first retry, 2 = second retry).

    Exponential with a small random jitter added on top, to avoid many
    concurrent requests retrying in lockstep during genuine provider-wide
    congestion (the exact failure mode this feature targets).
    """
    base = min(_BASE_DELAY_SECONDS * (_BACKOFF_FACTOR ** (retry_number - 1)), _MAX_DELAY_SECONDS)
    return base + random.uniform(0, _JITTER_SECONDS)


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

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return await provider.generate(request, credential_override)
            except AIProviderUnavailableError as exc:
                if attempt >= _MAX_ATTEMPTS:
                    raise
                logger.warning(
                    "transient AI provider failure, retrying "
                    "(provider_id=%s, model_id=%s, attempt=%d, exception=%s)",
                    request.provider_id,
                    request.model_id,
                    attempt,
                    type(exc).__name__,
                )
                await asyncio.sleep(_backoff_delay(attempt))
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

    async def stream(
        self, request: AIRequest, credential_override: str | None = None
    ) -> AsyncGenerator[AIStreamEvent, None]:
        """Streaming variant of generate — yields normalized AIStreamEvents.

        Retries the underlying provider.stream() call (a fresh connection)
        on AIProviderUnavailableError only while zero token-type events have
        been forwarded to the caller yet in this invocation — not based on
        exception type or elapsed time alone. The moment one token event is
        yielded, the retry window closes permanently for this call; any
        later failure propagates exactly as it did before this feature.
        Non-token events (e.g. an adapter-internal "start", which fires
        before any HTTP call is made) never close the retry window by
        themselves.
        """
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

        token_forwarded = False
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                async for event in provider.stream(request, credential_override):
                    if event.type.value == "token":
                        token_forwarded = True
                    yield event
                return
            except AIProviderUnavailableError as exc:
                if token_forwarded or attempt >= _MAX_ATTEMPTS:
                    raise
                logger.warning(
                    "transient AI provider failure during stream, retrying "
                    "(provider_id=%s, model_id=%s, attempt=%d, exception=%s)",
                    request.provider_id,
                    request.model_id,
                    attempt,
                    type(exc).__name__,
                )
                await asyncio.sleep(_backoff_delay(attempt))
