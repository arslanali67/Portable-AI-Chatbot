"""Message repository — scoped through conversation ownership."""

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message
from app.models.enums import MessageRole


class MessageRepository:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def create(
        self,
        *,
        conversation_id: int,
        role: MessageRole,
        content: str,
        sequence_number: int,
        metadata: dict[str, Any] | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            sequence_number=sequence_number,
            metadata_json=metadata,
        )
        self.db.add(message)
        # Single seam for every message-creation call site (chat_runtime.py's
        # user + assistant inserts, MessageService's user-message insert, and
        # the public widget path via ChatRuntimeService) so the conversation
        # list can sort by last activity, not just creation order.
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=func.now())
        )
        return message

    async def get_latest_sequence(self, conversation_id: int) -> int:
        latest = await self.db.scalar(
            select(func.max(Message.sequence_number)).where(
                Message.conversation_id == conversation_id
            )
        )
        return latest or 0

    async def list_for_conversation(
        self, conversation_id: int, *, limit: int, offset: int
    ) -> tuple[list[Message], int]:
        total = await self.db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.sequence_number.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total or 0
