"""Deterministic offline fake provider for tests and local development.

No network, no API key. Response mirrors the last user message so switching
providers is observable without any gateway changes.
"""

from typing import AsyncGenerator

from app.ai.contracts import AIRequest, AIResponse, AIUsage
from app.ai.metadata import ProviderMetadata
from app.ai.streaming import AIStreamEvent, AIStreamEventType


class FakeAIProvider:
    def __init__(self, metadata: ProviderMetadata, label: str) -> None:
        self.metadata = metadata
        self.label = label

    async def generate(self, request: AIRequest) -> AIResponse:
        content = self._full_content(request)
        return AIResponse(
            content=content,
            provider_id=request.provider_id,
            model_id=request.model_id,
            finish_reason="stop",
            usage=AIUsage(input_tokens=10, output_tokens=len(content.split())),
            metadata={"fake": True, "label": self.label},
        )

    def stream(self, request: AIRequest) -> AsyncGenerator[AIStreamEvent, None]:
        content = self._full_content(request)

        async def _gen() -> AsyncGenerator[AIStreamEvent, None]:
            yield AIStreamEvent(type=AIStreamEventType.START, data={"provider_id": request.provider_id, "model_id": request.model_id})
            for token in content.split(" "):
                yield AIStreamEvent(type=AIStreamEventType.TOKEN, data={"delta": token + " "})
            yield AIStreamEvent(
                type=AIStreamEventType.END,
                data={
                    "finish_reason": "stop",
                    "usage": {"input_tokens": 10, "output_tokens": len(content.split())},
                },
            )

        return _gen()

    def _full_content(self, request: AIRequest) -> str:
        last_user = next(
            (m.content for m in reversed(request.messages) if m.role.value == "user"),
            "",
        )
        return f"[{self.label}] {last_user}"
