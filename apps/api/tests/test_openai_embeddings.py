"""Real embedding provider tests — mocked HTTP, no network/key."""

import pytest
from httpx import AsyncClient, Response

from app.rag.embeddings import EmbeddingMetadata
from app.rag.openai_embeddings import (
    EmbeddingDimensionError,
    OpenAIEmbeddingError,
    OpenAIEmbeddingProvider,
)


def _provider(client) -> OpenAIEmbeddingProvider:
    return OpenAIEmbeddingProvider(
        EmbeddingMetadata(provider_id="openai", model_id="text-embedding-3-small", dimensions=384),
        api_key="sk-test-secret",
        base_url="https://api.example.com/v1",
        timeout=30.0,
        model="text-embedding-3-small",
        client=client,
    )


class MockTransport:
    def __init__(self, response: Response | None = None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        if self._error:
            raise self._error
        return self._response


def _ok_response():
    return Response(
        200,
        json={
            "data": [
                {"index": 0, "embedding": [0.1] * 384},
                {"index": 1, "embedding": [0.2] * 384},
            ]
        },
    )


async def _embed(transport, texts=None):
    provider = _provider(AsyncClient(transport=transport))
    return provider, await provider.embed_texts(texts or ["a", "b"])


@pytest.mark.asyncio
async def test_request_payload_and_model() -> None:
    t = MockTransport(_ok_response())
    await _embed(t)
    req = t.requests[0]
    assert str(req.url) == "https://api.example.com/v1/embeddings"
    assert req.headers["Authorization"] == "Bearer sk-test-secret"
    import json

    payload = json.loads(req.content)
    assert payload["model"] == "text-embedding-3-small"
    assert payload["input"] == ["a", "b"]


@pytest.mark.asyncio
async def test_vector_parsing_and_dimension() -> None:
    _, vectors = await _embed(MockTransport(_ok_response()))
    assert len(vectors) == 2
    assert all(len(v) == 384 for v in vectors)


@pytest.mark.asyncio
async def test_dimension_mismatch_rejected() -> None:
    bad = Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 100}]})
    with pytest.raises(EmbeddingDimensionError):
        await _embed(MockTransport(bad), texts=["x"])


@pytest.mark.asyncio
async def test_auth_failure() -> None:
    with pytest.raises(OpenAIEmbeddingError):
        await _embed(MockTransport(Response(401, json={})))


@pytest.mark.asyncio
async def test_rate_limit() -> None:
    with pytest.raises(OpenAIEmbeddingError):
        await _embed(MockTransport(Response(429, json={})))


@pytest.mark.asyncio
async def test_timeout() -> None:
    import httpx

    with pytest.raises(OpenAIEmbeddingError):
        await _embed(MockTransport(error=httpx.ConnectTimeout("timeout")))


@pytest.mark.asyncio
async def test_malformed_response() -> None:
    with pytest.raises(OpenAIEmbeddingError):
        await _embed(MockTransport(Response(200, json={"unexpected": True})))


@pytest.mark.asyncio
async def test_no_api_key_leakage() -> None:
    t = MockTransport(Response(401, json={}))
    with pytest.raises(OpenAIEmbeddingError) as exc_info:
        await _embed(t)
    assert "sk-test-secret" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_no_raw_response_leakage() -> None:
    _, vectors = await _embed(MockTransport(_ok_response()))
    assert str(vectors) == str([[0.1] * 384, [0.2] * 384])
