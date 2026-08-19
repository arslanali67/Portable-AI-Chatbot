"""Knowledge service — text + file ingestion, dedup, tenant/chatbot scoped.

Pipeline: (text | extract) → normalize → chunk → embed → store → ready.
"""

import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import KnowledgeDocument
from app.rag.chunker import Chunker, TextChunk
from app.rag.html_extractor import HTMLTextExtractor
from app.rag.http_fetcher import FetchError, SecureHTTPFetcher
from app.rag.normalizer import EmptyTextError, normalize_text
from app.rag.registry import get_embedding_provider
from app.rag.url_validator import InvalidURLError, UnsafeURLError
from app.rag.text_extractor import (
    DocumentTextExtractor,
    EmptyExtractedTextError,
    UnsupportedFileError as ExtractorUnsupportedFileError,
)
from app.repositories.chatbot import ChatbotRepository
from app.repositories.chunk import ChunkRepository
from app.repositories.knowledge_document import KnowledgeDocumentRepository
from app.schemas.knowledge import KnowledgeDocumentCreate, KnowledgeURLCreate


class ChatbotNotFoundError(Exception):
    pass


class DocumentNotFoundError(Exception):
    pass


class EmptyContentError(Exception):
    pass


class DuplicateDocumentError(Exception):
    pass


class UnsupportedFileError(Exception):
    pass


class FileTooLargeError(Exception):
    pass


class EmptyFileError(Exception):
    pass


class URLFetchError(Exception):
    pass


class KnowledgeService:
    def __init__(
        self,
        db_session: AsyncSession,
        fetcher: SecureHTTPFetcher | None = None,
    ):
        self.chatbots = ChatbotRepository(db_session)
        self.documents = KnowledgeDocumentRepository(db_session)
        self.chunks = ChunkRepository(db_session)
        self.extractor = DocumentTextExtractor()
        self.fetcher = fetcher or SecureHTTPFetcher()
        self.html_extractor = HTMLTextExtractor()

    async def ingest_text(
        self, organization_id: int, chatbot_id: int, payload: KnowledgeDocumentCreate
    ) -> KnowledgeDocument:
        await self._verify_chatbot(organization_id, chatbot_id)
        normalized = normalize_text(payload.content)
        content_hash = self._hash(normalized)
        await self._check_duplicate(organization_id, chatbot_id, content_hash)

        document = await self.documents.create(
            organization_id=organization_id,
            chatbot_id=chatbot_id,
            name=payload.name,
            source_type=payload.source_type,
            status="pending",
            content_hash=content_hash,
        )
        await self.documents.db.flush()
        await self._run_pipeline(document, normalized)
        return document

    async def ingest_file(
        self,
        organization_id: int,
        chatbot_id: int,
        *,
        filename: str,
        content: bytes,
        title: str | None,
    ) -> KnowledgeDocument:
        await self._verify_chatbot(organization_id, chatbot_id)

        if len(content) > settings.max_file_size_bytes:
            raise FileTooLargeError()
        if not content:
            raise EmptyFileError()

        try:
            extracted = self.extractor.extract(filename, content)
        except ExtractorUnsupportedFileError:
            raise UnsupportedFileError() from None
        except EmptyExtractedTextError as exc:
            raise EmptyContentError() from exc
        if len(extracted.text) > settings.max_extracted_text_chars:
            raise EmptyContentError()

        normalized = normalize_text(extracted.text)
        content_hash = self._hash(normalized)
        await self._check_duplicate(organization_id, chatbot_id, content_hash)

        safe_filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        document = await self.documents.create(
            organization_id=organization_id,
            chatbot_id=chatbot_id,
            name=title or safe_filename,
            source_type="file",
            status="pending",
            original_filename=safe_filename,
            file_size=len(content),
            content_hash=content_hash,
        )
        await self.documents.db.flush()
        await self._run_pipeline(document, normalized)
        return document

    async def ingest_url(
        self, organization_id: int, chatbot_id: int, payload: KnowledgeURLCreate
    ) -> KnowledgeDocument:
        await self._verify_chatbot(organization_id, chatbot_id)

        try:
            canonical, html = await self.fetcher.fetch_html(payload.url)
        except (FetchError, InvalidURLError, UnsafeURLError) as exc:
            raise URLFetchError() from exc
        try:
            extracted = self.html_extractor.extract(html)
        except Exception as exc:
            raise URLFetchError() from exc
        if len(extracted) > settings.max_extracted_text_chars:
            raise URLFetchError()

        normalized = normalize_text(extracted)
        content_hash = self._hash(normalized)
        await self._check_duplicate(organization_id, chatbot_id, content_hash)

        document = await self.documents.create(
            organization_id=organization_id,
            chatbot_id=chatbot_id,
            name=payload.title or canonical,
            source_type="url",
            status="pending",
            source_uri=canonical,
            content_hash=content_hash,
        )
        await self.documents.db.flush()
        await self._run_pipeline(document, normalized)
        return document

    async def _run_pipeline(self, document: KnowledgeDocument, normalized: str) -> None:
        try:
            chunker = Chunker(chunk_size=settings.chunk_size, overlap=settings.chunk_overlap)
            chunks: list[TextChunk] = chunker.chunk(normalized)
            provider = get_embedding_provider(settings.embedding_provider_id)
            vectors = await provider.embed_texts([c.content for c in chunks])

            for chunk, vector in zip(chunks, vectors):
                await self.chunks.create(
                    document_id=document.id,
                    organization_id=document.organization_id,
                    chatbot_id=document.chatbot_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    vector=vector,
                    metadata={"chunk_index": chunk.chunk_index},
                )

            document.status = "ready"
            await self.documents.db.commit()
        except EmptyTextError:
            document.status = "failed"
            await self.documents.db.commit()
            raise EmptyContentError()
        except Exception:
            document.status = "failed"
            await self.documents.db.commit()
            raise

        await self.documents.db.refresh(document)

    async def _verify_chatbot(self, organization_id: int, chatbot_id: int) -> None:
        chatbot = await self.chatbots.get_by_id_for_organization(organization_id, chatbot_id)
        if chatbot is None:
            raise ChatbotNotFoundError()

    async def _check_duplicate(
        self, organization_id: int, chatbot_id: int, content_hash: str
    ) -> None:
        existing = await self.documents.get_by_hash_for_scope(
            organization_id, chatbot_id, content_hash
        )
        if existing is not None:
            raise DuplicateDocumentError()

    @staticmethod
    def _hash(normalized_text: str) -> str:
        return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()

    async def get(self, organization_id: int, chatbot_id: int, document_id: int) -> KnowledgeDocument:
        document = await self.documents.get_by_scope(organization_id, chatbot_id, document_id)
        if document is None:
            raise DocumentNotFoundError()
        return document

    async def list(self, organization_id: int, chatbot_id: int) -> tuple[list[KnowledgeDocument], int]:
        return await self.documents.list_by_scope(organization_id, chatbot_id)

    async def delete(self, organization_id: int, chatbot_id: int, document_id: int) -> None:
        document = await self.get(organization_id, chatbot_id, document_id)
        await self.chunks.delete_for_document(document.id)
        await self.documents.delete(document)
        await self.documents.db.commit()

    async def chunk_count(self, document_id: int) -> int:
        return await self.chunks.count_for_document(document_id)
