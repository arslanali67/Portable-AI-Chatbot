"""Chat runtime schemas.

Client sends only content. Server owns conversation/chatbot/org, roles,
sequences, provider/model selection and system prompt.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import MessageRole
from app.schemas.conversation import MessageResponse


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20000)

    @field_validator("content")
    @classmethod
    def content_not_whitespace(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be empty or whitespace")
        return value


class ChatRuntimeMessage(BaseModel):
    """Safe message DTO for the runtime response (never raw DB/provider)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    role: MessageRole
    content: str
    sequence_number: int


class ChatResponse(BaseModel):
    conversation_id: int
    user_message: MessageResponse
    assistant_message: MessageResponse
