"""search_knowledge_base — wraps the existing RetrievalService.

organization_id/chatbot_id are supplied by the execution loop from the
current turn's trusted server-side context — never read from model-supplied
tool-call arguments anywhere in this file — so this tool cannot be pointed
at a different tenant's data no matter what arguments a confused or
manipulated model sends. Reuses RetrievalService's own tenant-scoped
search with zero duplicated retrieval logic.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tools.base import ToolExecutionError
from app.services.retrieval import ChatbotNotFoundError, RetrievalService


class KnowledgeSearchTool:
    name = "search_knowledge_base"
    description = "Search this chatbot's own knowledge base for relevant information."
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "top_k": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "description": "How many results to return (default 5).",
            },
        },
        "required": ["query"],
    }

    async def execute(
        self,
        arguments: dict[str, Any],
        *,
        organization_id: int,
        chatbot_id: int,
        db_session: AsyncSession,
    ) -> str:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolExecutionError("'query' is required and must be a non-empty string")

        top_k = arguments.get("top_k", 5)
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not (1 <= top_k <= 10):
            raise ToolExecutionError("'top_k' must be an integer between 1 and 10")

        try:
            results = await RetrievalService(db_session).search(
                organization_id, chatbot_id, query, top_k
            )
        except ChatbotNotFoundError as exc:
            raise ToolExecutionError("chatbot configuration not found") from exc

        if not results:
            return "No relevant results found in the knowledge base."

        return "\n\n".join(f"[{i + 1}] {r.content}" for i, r in enumerate(results))
