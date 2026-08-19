"""Document chunk repository — scoped storage + pgvector search."""

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentChunk


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
        query_vector: list[float],
        top_k: int,
    ) -> list[tuple[DocumentChunk, float]]:
        distance = DocumentChunk.vector.cosine_distance(query_vector)
        result = await self.db.execute(
            select(DocumentChunk, distance.label("distance"))
            .where(
                DocumentChunk.organization_id == organization_id,
                DocumentChunk.chatbot_id == chatbot_id,
            )
            .order_by(distance.asc())
            .limit(top_k)
        )
        return [(row[0], float(row[1])) for row in result.all()]

    async def delete_for_document(self, document_id: int) -> None:
        await self.db.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
