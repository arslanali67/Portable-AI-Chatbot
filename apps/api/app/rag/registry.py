"""Embedding registry and default providers."""

from app.core.config import settings
from app.rag.embeddings import EmbeddingMetadata
from app.rag.fake_embeddings import FakeEmbeddingProvider
from app.rag.openai_embeddings import OpenAIEmbeddingProvider


class EmbeddingRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, object] = {}

    def register(self, provider) -> None:
        self._providers[provider.metadata.provider_id] = provider

    def get(self, provider_id: str) -> object:
        if provider_id not in self._providers:
            raise KeyError(f"unknown embedding provider: {provider_id}")
        return self._providers[provider_id]

    def list(self) -> list[object]:
        return list(self._providers.values())


def build_embedding_registry() -> EmbeddingRegistry:
    registry = EmbeddingRegistry()
    registry.register(
        FakeEmbeddingProvider(
            EmbeddingMetadata(
                provider_id="fake",
                model_id=settings.embedding_model_id,
                dimensions=settings.embedding_dimensions,
            )
        )
    )
    registry.register(
        OpenAIEmbeddingProvider(
            EmbeddingMetadata(
                provider_id="openai",
                model_id=settings.openai_embedding_model,
                dimensions=settings.embedding_dimensions,
            ),
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=settings.openai_embedding_timeout,
            model=settings.openai_embedding_model,
        )
    )
    return registry


embedding_registry = build_embedding_registry()


def get_embedding_provider(provider_id: str):
    """Resolve provider; raise clear error if unavailable/disabled."""
    provider = embedding_registry.get(provider_id)
    if provider_id == "openai" and not settings.openai_api_key:
        raise ValueError("openai embedding provider is disabled: no API key configured")
    return provider
