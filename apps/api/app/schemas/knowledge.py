"""Knowledge/RAG schemas.

Server owns status, chunk indexes, embeddings, org/chatbot scoping.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

SOURCE_TYPES = {"text", "file", "url"}


class KnowledgeDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=500_000)
    source_type: str = "text"

    @field_validator("source_type")
    @classmethod
    def source_type_valid(cls, value: str) -> str:
        if value not in SOURCE_TYPES:
            raise ValueError(f"invalid source_type: {value}")
        return value

    @field_validator("content")
    @classmethod
    def content_not_whitespace(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be empty or whitespace")
        return value


class KnowledgeURLCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2000)
    title: str | None = Field(default=None, min_length=1, max_length=255)


class KnowledgeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source_type: str
    status: str
    chunk_count: int
    original_filename: str | None = None
    source_uri: str | None = None
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentListResponse(BaseModel):
    items: list[KnowledgeDocumentResponse]
    total: int


class KnowledgeCrawlResponse(BaseModel):
    documents: list[KnowledgeDocumentResponse]
    pages_fetched: int
    pages_ingested: int
    pages_skipped: int
    pages_failed: int
    stopped_reason: str


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=5000)
    top_k: int = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def query_not_whitespace(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be empty or whitespace")
        return value


class RetrievedChunkResponse(BaseModel):
    document_id: int
    chunk_id: int
    content: str
    score: float
    metadata: dict | None = None


class KnowledgeSearchResponse(BaseModel):
    results: list[RetrievedChunkResponse]
