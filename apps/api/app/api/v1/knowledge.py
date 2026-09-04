"""Knowledge endpoints — text ingestion, document reads, delete, retrieval.

All routes require organization membership and scope every query by
organization_id + chatbot_id. Vectors never returned.
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_organization_role
from app.core.rate_limit import crawl_rate_limiter
from app.models import Membership
from app.models.enums import MembershipRole
from app.schemas.knowledge import (
    KnowledgeCrawlResponse,
    KnowledgeDocumentCreate,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeURLCreate,
)
from app.services.knowledge import (
    ChatbotNotFoundError,
    DocumentNotFoundError,
    DuplicateDocumentError,
    EmptyContentError,
    EmptyFileError,
    FileTooLargeError,
    KnowledgeService,
    UnsupportedFileError,
    URLFetchError,
)
from app.services.retrieval import (
    ChatbotNotFoundError as RetrievalChatbotNotFoundError,
    RetrievalService,
)

router = APIRouter(
    prefix="/organizations/{organization_id}/chatbots/{chatbot_id}/knowledge",
    tags=["knowledge"],
)

require_member = Depends(require_organization_role(MembershipRole.MEMBER))


def _chatbot_404() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found")


def _document_404() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")


@router.post(
    "/documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_document(
    organization_id: int,
    chatbot_id: int,
    payload: KnowledgeDocumentCreate,
    _membership: Membership = require_member,
    db: AsyncSession = Depends(get_db),
):
    try:
        document = await KnowledgeService(db).ingest_text(
            organization_id, chatbot_id, payload
        )
    except ChatbotNotFoundError:
        raise _chatbot_404()
    except EmptyContentError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Content is empty")
    except DuplicateDocumentError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate content for this chatbot")
    return await _with_chunk_count(db, organization_id, chatbot_id, document)


@router.post(
    "/documents/file",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_file(
    organization_id: int,
    chatbot_id: int,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    _membership: Membership = require_member,
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    try:
        document = await KnowledgeService(db).ingest_file(
            organization_id,
            chatbot_id,
            filename=file.filename or "",
            content=content,
            title=title,
        )
    except ChatbotNotFoundError:
        raise _chatbot_404()
    except UnsupportedFileError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported file type"
        )
    except EmptyFileError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="File is empty")
    except EmptyContentError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File produced no usable text",
        )
    except FileTooLargeError:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large")
    except DuplicateDocumentError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate content for this chatbot")
    return await _with_chunk_count(db, organization_id, chatbot_id, document)


@router.post(
    "/documents/url",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_url(
    organization_id: int,
    chatbot_id: int,
    payload: KnowledgeURLCreate,
    _membership: Membership = require_member,
    db: AsyncSession = Depends(get_db),
):
    try:
        document = await KnowledgeService(db).ingest_url(
            organization_id, chatbot_id, payload
        )
    except ChatbotNotFoundError:
        raise _chatbot_404()
    except URLFetchError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="URL could not be ingested safely",
        )
    except DuplicateDocumentError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate content for this chatbot")
    return await _with_chunk_count(db, organization_id, chatbot_id, document)


@router.post("/documents/crawl", response_model=KnowledgeCrawlResponse, status_code=status.HTTP_201_CREATED)
async def crawl_url(
    organization_id: int,
    chatbot_id: int,
    payload: KnowledgeURLCreate,
    _membership: Membership = require_member,
    db: AsyncSession = Depends(get_db),
):
    if not crawl_rate_limiter.allow(f"org:{organization_id}"):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
    try:
        result = await KnowledgeService(db).crawl(organization_id, chatbot_id, payload)
    except ChatbotNotFoundError:
        raise _chatbot_404()
    except URLFetchError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="URL could not be ingested safely",
        )
    documents = [
        await _with_chunk_count(db, organization_id, chatbot_id, d) for d in result.documents
    ]
    return KnowledgeCrawlResponse(
        documents=documents,
        pages_fetched=result.pages_fetched,
        pages_ingested=result.pages_ingested,
        pages_skipped=result.pages_skipped,
        pages_failed=result.pages_failed,
        stopped_reason=result.stopped_reason,
    )


@router.get("/documents", response_model=KnowledgeDocumentListResponse)
async def list_documents(
    organization_id: int,
    chatbot_id: int,
    _membership: Membership = require_member,
    db: AsyncSession = Depends(get_db),
):
    service = KnowledgeService(db)
    documents, total = await service.list(organization_id, chatbot_id)
    items = [
        await _with_chunk_count(db, organization_id, chatbot_id, d) for d in documents
    ]
    return KnowledgeDocumentListResponse(items=items, total=total)


@router.get("/documents/{document_id}", response_model=KnowledgeDocumentResponse)
async def get_document(
    organization_id: int,
    chatbot_id: int,
    document_id: int,
    _membership: Membership = require_member,
    db: AsyncSession = Depends(get_db),
):
    try:
        document = await KnowledgeService(db).get(organization_id, chatbot_id, document_id)
    except DocumentNotFoundError:
        raise _document_404()
    return await _with_chunk_count(db, organization_id, chatbot_id, document)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    organization_id: int,
    chatbot_id: int,
    document_id: int,
    _membership: Membership = require_member,
    db: AsyncSession = Depends(get_db),
):
    try:
        await KnowledgeService(db).delete(organization_id, chatbot_id, document_id)
    except DocumentNotFoundError:
        raise _document_404()


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    organization_id: int,
    chatbot_id: int,
    payload: KnowledgeSearchRequest,
    _membership: Membership = require_member,
    db: AsyncSession = Depends(get_db),
):
    try:
        results = await RetrievalService(db).search(
            organization_id, chatbot_id, payload.query, payload.top_k
        )
    except RetrievalChatbotNotFoundError:
        raise _chatbot_404()
    return KnowledgeSearchResponse(results=results)


async def _with_chunk_count(db, organization_id: int, chatbot_id: int, document):
    count = await KnowledgeService(db).chunk_count(document.id)
    response = KnowledgeDocumentResponse(
        id=document.id,
        name=document.name,
        source_type=document.source_type,
        status=document.status,
        chunk_count=count,
        original_filename=document.original_filename,
        source_uri=document.source_uri,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )
    return response
