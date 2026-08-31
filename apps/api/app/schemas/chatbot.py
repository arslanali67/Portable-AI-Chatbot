"""Chatbot schemas.

Provider-agnostic configuration DTOs. Never expose secrets; status is not
freely choosable on create (starts as draft).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ChatbotStatus, ChatbotVisibility

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
LANGUAGES = {"en", "ur"}
ID_PATTERN = r"^[a-zA-Z0-9._-]+$"


class ChatbotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern=SLUG_PATTERN)
    description: str = Field(default="", max_length=5000)
    system_prompt: str = Field(default="", max_length=20000)
    welcome_message: str = Field(default="", max_length=2000)
    language: str = Field(default="en", min_length=2, max_length=10)
    visibility: ChatbotVisibility = ChatbotVisibility.PRIVATE
    provider_id: str = Field(
        default="fake-a", min_length=1, max_length=100, pattern=ID_PATTERN
    )
    model_id: str = Field(
        default="fake-model-small", min_length=1, max_length=100, pattern=ID_PATTERN
    )
    rag_enabled: bool = True
    rag_top_k: int | None = Field(default=None, ge=1, le=20)

    @field_validator("language")
    @classmethod
    def language_must_be_supported(cls, value: str) -> str:
        if value.lower() not in LANGUAGES:
            raise ValueError(f"unsupported language: {value}")
        return value.lower()


class ChatbotUpdate(BaseModel):
    """Partial update — only configuration fields may change."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=100, pattern=SLUG_PATTERN)
    description: str | None = Field(default=None, max_length=5000)
    system_prompt: str | None = Field(default=None, max_length=20000)
    welcome_message: str | None = Field(default=None, max_length=2000)
    language: str | None = Field(default=None, min_length=2, max_length=10)
    visibility: ChatbotVisibility | None = None
    provider_id: str | None = Field(default=None, min_length=1, max_length=100, pattern=ID_PATTERN)
    model_id: str | None = Field(default=None, min_length=1, max_length=100, pattern=ID_PATTERN)
    rag_enabled: bool | None = None
    rag_top_k: int | None = Field(default=None, ge=1, le=20)

    @field_validator("language")
    @classmethod
    def language_must_be_supported(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.lower() not in LANGUAGES:
            raise ValueError(f"unsupported language: {value}")
        return value.lower()


class ChatbotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    name: str
    slug: str
    description: str
    system_prompt: str
    welcome_message: str
    status: ChatbotStatus
    visibility: ChatbotVisibility
    language: str
    provider_id: str
    model_id: str
    rag_enabled: bool
    rag_top_k: int | None
    created_at: datetime
    updated_at: datetime
