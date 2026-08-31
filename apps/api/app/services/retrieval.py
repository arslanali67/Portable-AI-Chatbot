"""Retrieval service — tenant/chatbot-scoped pgvector similarity search.

Clean seam for future RAG integration into ChatRuntime (not wired yet).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.rag.registry import get_embedding_provider
from app.repositories.chatbot import ChatbotRepository
from app.repositories.chunk import ChunkRepository
from app.schemas.knowledge import RetrievedChunkResponse


class ChatbotNotFoundError(Exception):
    pass


class RetrievalService:
    def __init__(self, db_session: AsyncSession):
        self.chatbots = ChatbotRepository(db_session)
        self.chunks = ChunkRepository(db_session)

    async def search(
        self, organization_id: int, chatbot_id: int, query: str, top_k: int
    ) -> list[RetrievedChunkResponse]:
        chatbot = await self.chatbots.get_by_id_for_organization(organization_id, chatbot_id)
        if chatbot is None:
            raise ChatbotNotFoundError()

        provider = get_embedding_provider(settings.embedding_provider_id)
        query_vector = (await provider.embed_texts([query]))[0]

        rows = await self.chunks.search(
            organization_id, chatbot_id, query, query_vector, top_k
        )
        return [
            RetrievedChunkResponse(
                document_id=chunk.document_id,
                chunk_id=chunk.id,
                content=chunk.content,
                score=score,
                metadata=chunk.metadata_json,
            )
            for chunk, score in rows
        ]
