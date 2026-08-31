"""Document chunk repository — scoped storage + hybrid (vector + full-text) search."""

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentChunk

# Reciprocal Rank Fusion constant (standard default from the RRF paper).
RRF_K = 60
# Each candidate query over-fetches top_k * this factor before fusion.
CANDIDATE_POOL_MULTIPLIER = 4


class ChunkRepository:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def create(
        self,
        *,
        document_id: int,
        organization_id: int,
        chatbot_id: int,
        chunk_index: int,
        content: str,
        vector: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> DocumentChunk:
        chunk = DocumentChunk(
            document_id=document_id,
            organization_id=organization_id,
            chatbot_id=chatbot_id,
            chunk_index=chunk_index,
            content=content,
            metadata_json=metadata,
            vector=vector,
        )
        self.db.add(chunk)
        return chunk

    async def count_for_document(self, document_id: int) -> int:
        return (
            await self.db.scalar(
                select(func.count()).select_from(DocumentChunk).where(
                    DocumentChunk.document_id == document_id
                )
            )
        ) or 0

    async def search(
        self,
        organization_id: int,
        chatbot_id: int,
        query_text: str,
        query_vector: list[float],
        top_k: int,
    ) -> list[tuple[DocumentChunk, float]]:
        """Hybrid search: fuse a vector-similarity candidate list and a
        full-text candidate list via Reciprocal Rank Fusion (RRF).

        Both candidate queries are independently scoped by
        organization_id/chatbot_id, so cross-tenant/cross-chatbot chunks
        can never enter the fused result even if they'd rank highly on
        either signal alone.
        """
        candidate_pool = top_k * CANDIDATE_POOL_MULTIPLIER

        distance = DocumentChunk.vector.cosine_distance(query_vector)
        vector_result = await self.db.execute(
            select(DocumentChunk)
            .where(
                DocumentChunk.organization_id == organization_id,
                DocumentChunk.chatbot_id == chatbot_id,
            )
            .order_by(distance.asc())
            .limit(candidate_pool)
        )
        vector_chunks = list(vector_result.scalars().all())

        tsquery = func.plainto_tsquery("english", query_text)
        rank = func.ts_rank_cd(DocumentChunk.content_tsv, tsquery)
        fts_result = await self.db.execute(
            select(DocumentChunk)
            .where(
                DocumentChunk.organization_id == organization_id,
                DocumentChunk.chatbot_id == chatbot_id,
                DocumentChunk.content_tsv.op("@@")(tsquery),
            )
            .order_by(rank.desc())
            .limit(candidate_pool)
        )
        fts_chunks = list(fts_result.scalars().all())

        fused_scores: dict[int, float] = {}
        chunks_by_id: dict[int, DocumentChunk] = {}
        for candidate_list in (vector_chunks, fts_chunks):
            for rank_index, chunk in enumerate(candidate_list, start=1):
                chunks_by_id[chunk.id] = chunk
                fused_scores[chunk.id] = fused_scores.get(chunk.id, 0.0) + 1.0 / (
                    RRF_K + rank_index
                )

        ranked_ids = sorted(
            fused_scores, key=lambda chunk_id: fused_scores[chunk_id], reverse=True
        )[:top_k]
        return [(chunks_by_id[chunk_id], fused_scores[chunk_id]) for chunk_id in ranked_ids]

    async def delete_for_document(self, document_id: int) -> None:
        await self.db.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
