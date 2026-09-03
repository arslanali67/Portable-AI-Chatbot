"""Tool interface — the platform-defined execution allowlist.

Every tool is a small, code-owned, vetted Python callable, registered in
`app/ai/tools/registry.py` — never an organization-defined or webhook-style
tool pointing at an external endpoint (that decision stands permanently).

Platform-context parameters (organization_id, chatbot_id, db_session) are
passed to execute() as keyword-only arguments, separate from model-supplied
`arguments` — the two are never merged, so a tool can never be pointed at a
different tenant's data via its arguments, structurally, not just by
validation.
"""

from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class ToolExecutionError(Exception):
    """Raised by a tool's execute() for an expected, safe-to-surface
    failure (invalid input, not found, ...). The execution loop catches
    this (and any other exception) and feeds a clean, generic error
    result back to the model — never a crash, never a raw traceback."""


class Tool(Protocol):
    name: str
    description: str
    parameters_schema: dict[str, Any]

    async def execute(
        self,
        arguments: dict[str, Any],
        *,
        organization_id: int,
        chatbot_id: int,
        db_session: AsyncSession,
    ) -> str: ...
