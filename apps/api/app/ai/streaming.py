"""Normalized streaming contract.

Provider-neutral stream events. Provider adapters convert their raw chunks
into these; application code never sees provider formats.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class AIStreamEventType(str, Enum):
    START = "start"
    TOKEN = "token"
    END = "end"
    ERROR = "error"


@dataclass(frozen=True)
class AIStreamEvent:
    type: AIStreamEventType
    data: dict[str, Any]
