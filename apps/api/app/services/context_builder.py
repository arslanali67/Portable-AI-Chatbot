"""Context builder — pure assembly of system prompt + RAG context + history.

No DB, no provider, no authorization. Retrieved chunks are untrusted reference
DATA clearly delimited; chatbot.system_prompt is always authoritative.
"""

from app.ai.contracts import AIMessage, AIMessageRole, AIRequest
from app.core.config import settings
from app.schemas.knowledge import RetrievedChunkResponse


class ContextBuilder:
    def __init__(self, top_k: int | None = None, max_context_chars: int | None = None) -> None:
        self.top_k = top_k if top_k is not None else settings.rag_top_k
        self.max_context_chars = (
            max_context_chars if max_context_chars is not None else settings.rag_max_context_chars
        )

    def build(
        self,
        *,
        provider_id: str,
        model_id: str,
        system_prompt: str | None,
        history: list[AIMessage],
        retrieved: list[RetrievedChunkResponse],
        latest_user_content: str,
    ) -> AIRequest:
        messages = list(history)  # history already includes the latest user message

        context = self._format_knowledge(retrieved[: self.top_k])
        if context:
            messages.append(AIMessage(role=AIMessageRole.USER, content=context))

        return AIRequest(
            provider_id=provider_id,
            model_id=model_id,
            messages=messages,
            system_prompt=system_prompt,
        )

    def _format_knowledge(self, chunks: list[RetrievedChunkResponse]) -> str:
        if not chunks:
            return ""
        parts = []
        budget = self.max_context_chars
        for index, chunk in enumerate(chunks, start=1):
            block = f"[Source {index}]\n{chunk.content}"
            if budget - len(block) < 0:
                break
            parts.append(block)
            budget -= len(block)
        if not parts:
            return ""
        return "<knowledge_context>\n" + "\n\n".join(parts) + "\n</knowledge_context>"
