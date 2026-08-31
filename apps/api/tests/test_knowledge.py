"""Knowledge/RAG tests — ingestion, retrieval, tenant isolation, delete,
embeddings. Deterministic (fake embeddings, no network).

Require Docker PostgreSQL + alembic upgrade head. Run: pytest -m identity
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.identity

client = TestClient(app)

PASSWORD = "strong-password-123"
_RUN = uuid.uuid4().hex[:8]


def _email(name: str) -> str:
    return f"{name}-{_RUN}@example.com"


def _slug(name: str) -> str:
    return f"{name}-{_RUN}"


def _register(email: str, full_name: str = "Knowledge Tester"):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": full_name},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _login(email: str) -> str:
    r = client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _setup() -> tuple[str, int, int]:
    email = _email(f"owner{uuid.uuid4().hex[:6]}")
    token = _login(_register(email)["email"])
    r = client.post(
        "/api/v1/organizations",
        json={"name": "Org", "slug": _slug(f"org{uuid.uuid4().hex[:6]}")},
        headers=_auth(token),
    )
    org_id = r.json()["id"]
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots",
        json={"name": "Bot", "slug": _slug(f"bot{uuid.uuid4().hex[:6]}")},
        headers=_auth(token),
    )
    return token, org_id, r.json()["id"]


def _ingest(token: str, org_id: int, bot_id: int, content: str = "Hello world.", name: str = "Doc", **overrides):
    payload = {"name": name, "content": content, "source_type": "text"}
    payload.update(overrides)
    return client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/knowledge/documents",
        json=payload,
        headers=_auth(token),
    )


def _search(token: str, org_id: int, bot_id: int, query: str, top_k: int = 5):
    return client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/knowledge/search",
        json={"query": query, "top_k": top_k},
        headers=_auth(token),
    )


async def _chunks(org_id: int, bot_id: int, doc_id: int) -> list[tuple[int, str]]:
    async with TestSessionLocal() as s:
        r = await s.execute(
            text(
                "SELECT chunk_index, content FROM document_chunks "
                "WHERE organization_id = :oid AND chatbot_id = :cid AND document_id = :did "
                "ORDER BY chunk_index"
            ),
            {"oid": org_id, "cid": bot_id, "did": doc_id},
        )
        return [(i, c) for i, c in r.fetchall()]


async def _vector_dims(org_id: int, bot_id: int, doc_id: int) -> int:
    async with TestSessionLocal() as s:
        r = await s.execute(
            text(
                "SELECT vector_dims(vector) FROM document_chunks "
                "WHERE organization_id = :oid AND chatbot_id = :cid AND document_id = :did "
                "LIMIT 1"
            ),
            {"oid": org_id, "cid": bot_id, "did": doc_id},
        )
        return r.scalar_one()


# --- Ingestion ---


def test_ingest_document_201() -> None:
    token, org_id, bot_id = _setup()
    r = _ingest(token, org_id, bot_id)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "ready"
    assert body["chunk_count"] >= 1
    assert body["source_type"] == "text"


def test_ingest_empty_content_422() -> None:
    token, org_id, bot_id = _setup()
    assert _ingest(token, org_id, bot_id, content="").status_code == 422


def test_ingest_whitespace_422() -> None:
    token, org_id, bot_id = _setup()
    assert _ingest(token, org_id, bot_id, content="   ").status_code == 422


def test_ingest_extra_fields_422() -> None:
    token, org_id, bot_id = _setup()
    assert (
        _ingest(token, org_id, bot_id, status="ready", chunk_index=5).status_code
        == 422
    )


def test_ingest_invalid_source_type_422() -> None:
    token, org_id, bot_id = _setup()
    assert _ingest(token, org_id, bot_id, source_type="pdf").status_code == 422


def test_chunks_created_ordered() -> None:
    import asyncio

    token, org_id, bot_id = _setup()
    long_content = " ".join([f"word{i}" for i in range(3000)])
    r = _ingest(token, org_id, bot_id, content=long_content)
    doc_id = r.json()["id"]
    chunks = asyncio.run(_chunks(org_id, bot_id, doc_id))
    assert len(chunks) > 1
    indexes = [i for i, _ in chunks]
    assert indexes == sorted(indexes)


def test_embeddings_generated_dimension() -> None:
    import asyncio

    token, org_id, bot_id = _setup()
    doc_id = _ingest(token, org_id, bot_id).json()["id"]
    assert asyncio.run(_vector_dims(org_id, bot_id, doc_id)) == 384


def test_document_becomes_ready() -> None:
    token, org_id, bot_id = _setup()
    r = _ingest(token, org_id, bot_id)
    assert r.json()["status"] == "ready"


# --- Retrieval ---


def test_search_returns_relevant_chunks() -> None:
    token, org_id, bot_id = _setup()
    _ingest(token, org_id, bot_id, content="The cat chases the red ball.")
    r = _search(token, org_id, bot_id, "cat ball")
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) >= 1
    assert all("score" in x for x in results)
    assert all("content" in x for x in results)


def test_search_top_k_works() -> None:
    token, org_id, bot_id = _setup()
    _ingest(token, org_id, bot_id, content=" ".join(f"tok{i}" for i in range(2000)))
    r = _search(token, org_id, bot_id, "tok5", top_k=3)
    assert len(r.json()["results"]) <= 3


def test_search_top_k_over_20_422() -> None:
    token, org_id, bot_id = _setup()
    assert _search(token, org_id, bot_id, "hello", top_k=21).status_code == 422


def test_search_empty_query_422() -> None:
    token, org_id, bot_id = _setup()
    assert _search(token, org_id, bot_id, "").status_code == 422
    assert _search(token, org_id, bot_id, "   ").status_code == 422


# --- Security / isolation ---


def test_unknown_chatbot_404() -> None:
    token, org_id, _ = _setup()
    assert _ingest(token, org_id, 999_999, content="x").status_code == 404
    assert _search(token, org_id, 999_999, "x").status_code == 404


# --- Hybrid search (vector + full-text via RRF) ---


def test_hybrid_search_combines_vector_and_fulltext_signals() -> None:
    """Proves fusion genuinely combines both signals rather than falling
    back to one.

    Query "quarterly archive" against four chunks:
    - V: contains "archive" verbatim (strong fake-embedding vector match)
      but no "quarter" stem anywhere -> fails the full-text AND-match
      entirely (verified live: `to_tsvector(...) @@ plainto_tsquery(...)`
      is false for this content), so V can ONLY ever surface via the
      vector signal.
    - F: contains "quarter" + "archiving" (stems to 'quarter' & 'archiv',
      matching both required terms) but shares zero literal tokens with
      the query, so its fake-embedding vector similarity is exactly 0
      (verified via the fake embedding's hash-based bag-of-words scheme)
      -> F can ONLY ever surface via the full-text signal.
    - D1/D2: share nothing with the query on either signal (distractors).

    If fusion silently ignored the vector signal, V (which never appears
    in the full-text candidate list) could never be returned at all. If
    fusion silently ignored full-text, F would rank no better than the
    distractors (all tied at zero vector similarity). The fused top-2
    result being exactly [F, V] is only possible if both signals are
    genuinely contributing.
    """
    token, org_id, bot_id = _setup()
    _ingest(token, org_id, bot_id, content="The archive stores old server logs and nightly backup snapshots.", name="V")
    _ingest(token, org_id, bot_id, content="Every quarter the finance team is archiving compliance records.", name="F")
    _ingest(token, org_id, bot_id, content="Weather forecasts predict light rain across the valley this weekend.", name="D1")
    _ingest(token, org_id, bot_id, content="The championship game ended with a dramatic overtime victory.", name="D2")

    r = _search(token, org_id, bot_id, "quarterly archive", top_k=2)
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 2
    contents = {row["content"] for row in results}
    assert contents == {
        "Every quarter the finance team is archiving compliance records.",
        "The archive stores old server logs and nightly backup snapshots.",
    }


def test_hybrid_search_top_k_respected_after_fusion() -> None:
    """More matching chunks exist than top_k; the final count is still
    exactly top_k after fusion, not the size of either candidate list."""
    token, org_id, bot_id = _setup()
    for i in range(5):
        _ingest(
            token,
            org_id,
            bot_id,
            content=f"Archive record number {i} about quarterly financial statements.",
            name=f"Doc{i}",
        )
    r = _search(token, org_id, bot_id, "quarterly archive", top_k=2)
    assert r.status_code == 200
    assert len(r.json()["results"]) == 2


def test_hybrid_search_tenant_isolation_enforced_on_both_signals() -> None:
    """A chunk that would rank well on full-text (not vector — shares no
    literal tokens with the query) must never leak across organizations
    or chatbots. Both candidate queries in the fusion are independently
    scoped, not just the vector one."""
    token_a, org_a, bot_a = _setup()
    token_b, org_b, bot_b = _setup()
    fts_relevant = "Every quarter the finance team is archiving compliance records."
    _ingest(token_b, org_b, bot_b, content=fts_relevant)
    r = _search(token_a, org_a, bot_a, "quarterly archive")
    assert r.status_code == 200
    assert r.json()["results"] == []

    # Same organization, different chatbot.
    r2 = client.post(
        f"/api/v1/organizations/{org_a}/chatbots",
        json={"name": "Bot2", "slug": _slug(f"bot2{uuid.uuid4().hex[:6]}")},
        headers=_auth(token_a),
    )
    bot_a2 = r2.json()["id"]
    _ingest(token_a, org_a, bot_a2, content=fts_relevant)
    r3 = _search(token_a, org_a, bot_a, "quarterly archive")
    assert r3.json()["results"] == []


def test_cross_org_document_access_denied() -> None:
    token_a, org_a, bot_a = _setup()
    token_b, org_b, bot_b = _setup()
    doc_id = _ingest(token_a, org_a, bot_a).json()["id"]
    # B tries A's document via B's org path.
    r = client.get(
        f"/api/v1/organizations/{org_b}/chatbots/{bot_b}/knowledge/documents/{doc_id}",
        headers=_auth(token_b),
    )
    assert r.status_code == 404
    # B tries A's org path (no membership).
    r2 = client.get(
        f"/api/v1/organizations/{org_a}/chatbots/{bot_a}/knowledge/documents/{doc_id}",
        headers=_auth(token_b),
    )
    assert r2.status_code == 403


def test_cross_org_retrieval_denied() -> None:
    token_a, org_a, bot_a = _setup()
    token_b, org_b, bot_b = _setup()
    _ingest(token_a, org_a, bot_a, content="secret data for A")
    r = _search(token_b, org_b, bot_b, "secret data for A")
    assert r.status_code == 200
    assert r.json()["results"] == []


def test_cross_chatbot_isolation() -> None:
    token, org_id, bot_a = _setup()
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots",
        json={"name": "Bot2", "slug": _slug(f"bot2{uuid.uuid4().hex[:6]}")},
        headers=_auth(token),
    )
    bot_b = r.json()["id"]
    doc_id = _ingest(token, org_id, bot_a, content="only in bot A").json()["id"]
    r = client.get(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_b}/knowledge/documents/{doc_id}",
        headers=_auth(token),
    )
    assert r.status_code == 404
    r2 = _search(token, org_id, bot_b, "only in bot A")
    assert r2.json()["results"] == []


def test_unknown_document_404() -> None:
    token, org_id, bot_id = _setup()
    r = client.get(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/knowledge/documents/999999",
        headers=_auth(token),
    )
    assert r.status_code == 404


def test_vectors_not_returned() -> None:
    token, org_id, bot_id = _setup()
    _ingest(token, org_id, bot_id)
    r = client.get(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/knowledge/documents",
        headers=_auth(token),
    )
    dumped = r.text.lower()
    assert "vector" not in dumped
    r2 = _search(token, org_id, bot_id, "hello")
    assert "vector" not in r2.text.lower()


def test_no_credentials_in_responses() -> None:
    token, org_id, bot_id = _setup()
    _ingest(token, org_id, bot_id)
    r = client.get(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/knowledge/documents",
        headers=_auth(token),
    )
    dumped = r.text.lower()
    assert "sk-" not in dumped
    assert "api_key" not in dumped
    assert "authorization" not in dumped


# --- Delete ---


def test_delete_removes_chunks_and_vectors() -> None:
    import asyncio

    token, org_id, bot_id = _setup()
    doc_id = _ingest(token, org_id, bot_id).json()["id"]
    r = client.delete(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/knowledge/documents/{doc_id}",
        headers=_auth(token),
    )
    assert r.status_code == 204
    assert asyncio.run(_chunks(org_id, bot_id, doc_id)) == []
    r2 = client.get(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/knowledge/documents/{doc_id}",
        headers=_auth(token),
    )
    assert r2.status_code == 404


# --- Embedding determinism ---


def test_fake_embedding_deterministic() -> None:
    from app.rag.fake_embeddings import FakeEmbeddingProvider
    from app.rag.embeddings import EmbeddingMetadata

    provider = FakeEmbeddingProvider(
        EmbeddingMetadata(provider_id="fake", model_id="fake-embed-v1", dimensions=384)
    )
    import asyncio

    a = asyncio.run(provider.embed_texts(["hello world"]))
    b = asyncio.run(provider.embed_texts(["hello world"]))
    assert a == b
    assert len(a[0]) == 384
