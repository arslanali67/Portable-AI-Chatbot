"""Embedding abstraction — provider-agnostic.

RAG/retrieval code never contains provider-specific embedding logic.
"""

from dataclasses import dataclass
from typing import Protocol

Vector = list[float]


class EmbeddingProvider(Protocol):
    metadata: "EmbeddingMetadata"

    async def embed_texts(self, texts: list[str]) -> list[Vector]: ...


@dataclass(frozen=True)
class EmbeddingMetadata:
    provider_id: str
    model_id: str
    dimensions: int
