"""Real OpenAI-compatible embedding provider.

httpx-based, explicit timeout, injectable client for tests, dimension
validation. Never leaks keys/raw responses.
"""

import json

import httpx

from app.rag.embeddings import EmbeddingMetadata, Vector


class EmbeddingDimensionError(Exception):
    pass


class OpenAIEmbeddingError(Exception):
    pass


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        metadata: EmbeddingMetadata,
        *,
        api_key: str,
        base_url: str,
        timeout: float,
        model: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.metadata = metadata
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._model = model
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def embed_texts(self, texts: list[str]) -> list[Vector]:
        if not texts:
            return []
        payload = {"model": self._model, "input": texts}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = await self._client.post(
                f"{self._base_url}/embeddings",
                headers=headers,
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise OpenAIEmbeddingError("embedding request timed out") from exc
        except httpx.HTTPError as exc:
            raise OpenAIEmbeddingError("embedding request failed") from exc

        if response.status_code == 401 or response.status_code == 403:
            raise OpenAIEmbeddingError("embedding authentication failed")
        if response.status_code == 429:
            raise OpenAIEmbeddingError("embedding rate limit exceeded")
        if response.status_code >= 500:
            raise OpenAIEmbeddingError("embedding provider unavailable")
        if not response.is_success:
            raise OpenAIEmbeddingError("embedding request rejected")

        try:
            data = response.json()
            items = data["data"]
            vectors = [item["embedding"] for item in sorted(items, key=lambda i: i["index"])]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise OpenAIEmbeddingError("malformed embedding response") from exc

        for vector in vectors:
            if len(vector) != self.metadata.dimensions:
                raise EmbeddingDimensionError(
                    f"embedding dimension mismatch: expected {self.metadata.dimensions}, got {len(vector)}"
                )
        return vectors
