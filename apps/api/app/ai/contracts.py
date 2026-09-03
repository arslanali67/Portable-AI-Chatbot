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
    TOOL = "tool"


@dataclass(frozen=True)
class AIToolCall:
    id: str
    name: str
    arguments: str  # raw, provider-returned JSON-encoded string — not parsed


@dataclass(frozen=True)
class AIMessage:
    role: AIMessageRole
    content: str
    # Only meaningful when role == ASSISTANT: the tool calls this message
    # requested, replayed so the provider can match a later TOOL message's
    # tool_call_id against them. Only meaningful when role == TOOL: which
    # tool call this message is the result of. Both additive/optional —
    # every existing call site (role in {SYSTEM, USER, ASSISTANT} with no
    # tool data) is unaffected. Contract-level only — never persisted to
    # the messages table (see ChatRuntimeService._run_with_tool_execution).
    tool_calls: list[AIToolCall] | None = None
    tool_call_id: str | None = None


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
    response_schema: dict[str, Any] | None = None
    tools: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class AIResponse:
    content: str
    provider_id: str
    model_id: str
    finish_reason: str
    usage: AIUsage
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[AIToolCall] | None = None
