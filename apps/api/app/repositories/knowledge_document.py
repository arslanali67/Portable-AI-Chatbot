"""Knowledge document repository — tenant/chatbot scoped."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeDocument


class KnowledgeDocumentRepository:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def create(
        self,
        *,
        organization_id: int,
        chatbot_id: int,
        name: str,
        source_type: str,
        status: str,
        source_uri: str | None = None,
        original_filename: str | None = None,
        file_size: int | None = None,
        content_hash: str | None = None,
        metadata_json: dict | None = None,
    ) -> KnowledgeDocument:
        document = KnowledgeDocument(
            organization_id=organization_id,
            chatbot_id=chatbot_id,
            name=name,
            source_type=source_type,
            status=status,
            source_uri=source_uri,
            original_filename=original_filename,
            file_size=file_size,
            content_hash=content_hash,
            metadata_json=metadata_json,
        )
        self.db.add(document)
        return document

    async def get_by_hash_for_scope(
        self, organization_id: int, chatbot_id: int, content_hash: str
    ) -> KnowledgeDocument | None:
        result = await self.db.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.organization_id == organization_id,
                KnowledgeDocument.chatbot_id == chatbot_id,
                KnowledgeDocument.content_hash == content_hash,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_scope(
        self, organization_id: int, chatbot_id: int, document_id: int
    ) -> KnowledgeDocument | None:
        result = await self.db.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id == document_id,
                KnowledgeDocument.organization_id == organization_id,
                KnowledgeDocument.chatbot_id == chatbot_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_scope(
        self, organization_id: int, chatbot_id: int
    ) -> tuple[list[KnowledgeDocument], int]:
        conditions = [
            KnowledgeDocument.organization_id == organization_id,
            KnowledgeDocument.chatbot_id == chatbot_id,
        ]
        total = await self.db.scalar(
            select(func.count()).select_from(KnowledgeDocument).where(*conditions)
        )
        result = await self.db.execute(
            select(KnowledgeDocument).where(*conditions).order_by(KnowledgeDocument.id)
        )
        return list(result.scalars().all()), total or 0

    async def delete(self, document: KnowledgeDocument) -> None:
        await self.db.delete(document)
