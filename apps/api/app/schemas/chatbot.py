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

MAX_PRESET_QUESTIONS = 10
MAX_PRESET_QUESTION_LENGTH = 200
MAX_PRESET_ANSWER_LENGTH = 2000


def _validate_preset_questions(value: list[dict] | None) -> list[dict] | None:
    """Shared by ChatbotCreate/ChatbotUpdate — reject clearly, don't
    silently accept (matches the tools/response_schema precedent), since
    unlike tools this renders directly to end users: unbounded count/
    length would visibly break the widget/console suggestion-chip UI."""
    if value is None:
        return None
    if len(value) > MAX_PRESET_QUESTIONS:
        raise ValueError(f"preset_questions: at most {MAX_PRESET_QUESTIONS} entries allowed")
    for i, item in enumerate(value):
        if not isinstance(item, dict) or set(item.keys()) != {"question", "answer"}:
            raise ValueError(f"preset_questions[{i}]: must have exactly 'question' and 'answer' keys")
        question, answer = item["question"], item["answer"]
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"preset_questions[{i}]: question must be a non-empty string")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError(f"preset_questions[{i}]: answer must be a non-empty string")
        if len(question) > MAX_PRESET_QUESTION_LENGTH:
            raise ValueError(
                f"preset_questions[{i}]: question exceeds {MAX_PRESET_QUESTION_LENGTH} characters"
            )
        if len(answer) > MAX_PRESET_ANSWER_LENGTH:
            raise ValueError(
                f"preset_questions[{i}]: answer exceeds {MAX_PRESET_ANSWER_LENGTH} characters"
            )
    return value


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
    response_schema: dict | None = None
    tools: list[dict] | None = None
    preset_questions: list[dict] | None = None

    @field_validator("language")
    @classmethod
    def language_must_be_supported(cls, value: str) -> str:
        if value.lower() not in LANGUAGES:
            raise ValueError(f"unsupported language: {value}")
        return value.lower()

    @field_validator("preset_questions")
    @classmethod
    def preset_questions_valid(cls, value: list[dict] | None) -> list[dict] | None:
        return _validate_preset_questions(value)


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
    response_schema: dict | None = None
    tools: list[dict] | None = None
    preset_questions: list[dict] | None = None

    @field_validator("language")
    @classmethod
    def language_must_be_supported(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.lower() not in LANGUAGES:
            raise ValueError(f"unsupported language: {value}")
        return value.lower()

    @field_validator("preset_questions")
    @classmethod
    def preset_questions_valid(cls, value: list[dict] | None) -> list[dict] | None:
        return _validate_preset_questions(value)


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
    response_schema: dict | None
    tools: list[dict] | None
    preset_questions: list[dict] | None
    created_at: datetime
    updated_at: datetime
