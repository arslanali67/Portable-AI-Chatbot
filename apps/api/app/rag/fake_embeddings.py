"""Deterministic offline fake embedding provider.

Stable vectors (hash-based), configured dimension, no network, no API key.
"""

import hashlib

from app.rag.embeddings import EmbeddingMetadata, Vector


class FakeEmbeddingProvider:
    def __init__(self, metadata: EmbeddingMetadata) -> None:
        self.metadata = metadata

    async def embed_texts(self, texts: list[str]) -> list[Vector]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> Vector:
        vector = [0.0] * self.metadata.dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.metadata.dimensions
            value = (int.from_bytes(digest[4:8], "big") / 2**32) - 0.5
            vector[index] += value
        norm = sum(v * v for v in vector) ** 0.5
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector
