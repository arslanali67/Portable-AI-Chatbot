"""Provider interface and OpenAI-compatible base.

Core contracts are provider-independent and depend on nothing from
FastAPI/SQLAlchemy/provider SDKs.
"""

from typing import AsyncGenerator, Protocol

from app.ai.contracts import AIRequest, AIResponse
from app.ai.metadata import ProviderMetadata
from app.ai.streaming import AIStreamEvent


class AIProvider(Protocol):
    metadata: ProviderMetadata

    async def generate(self, request: AIRequest) -> AIResponse: ...

    def stream(self, request: AIRequest) -> AsyncGenerator[AIStreamEvent, None]: ...


class OpenAICompatibleProvider:
    """Base for future OpenAI-compatible adapters (OpenAI, Kimi, DeepSeek,
    Qwen, Groq, custom endpoints).

    Subclasses implement `generate` using their own HTTP/SDK layer.
    """

    def __init__(self, metadata: ProviderMetadata) -> None:
        self.metadata = metadata

    async def generate(self, request: AIRequest) -> AIResponse:  # pragma: no cover
        raise NotImplementedError("subclass must implement generate")
