"""Public widget schemas — strict, client controls only public key/session/content/origin."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WidgetSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_key: str = Field(min_length=1, max_length=128)
    origin: str | None = Field(default=None, max_length=500)


class WidgetConfigResponse(BaseModel):
    chatbot_name: str
    welcome_message: str
    language: str
    enabled: bool
    theme_color: str | None = None
    widget_position: str | None = None
    avatar_url: str | None = None


class WidgetSessionResponse(BaseModel):
    session_token: str
    config: WidgetConfigResponse


class WidgetChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_token: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=20000)
    origin: str | None = Field(default=None, max_length=500)

    @field_validator("content")
    @classmethod
    def content_not_whitespace(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be empty or whitespace")
        return value
