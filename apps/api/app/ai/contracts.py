"""Provider-neutral AI contracts.

No FastAPI, SQLAlchemy, or provider SDK imports. Application talks to these
types only.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AIMessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    # Future: TOOL = "tool"


@dataclass(frozen=True)
class AIMessage:
    role: AIMessageRole
    content: str


@dataclass(frozen=True)
class AIUsage:
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class AIRequest:
    provider_id: str
    model_id: str
    messages: list[AIMessage]
    system_prompt: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AIResponse:
    content: str
    provider_id: str
    model_id: str
    finish_reason: str
    usage: AIUsage
    metadata: dict[str, Any] = field(default_factory=dict)
