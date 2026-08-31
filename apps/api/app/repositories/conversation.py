"""Conversation repository — tenant-scoped data access."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation


class ConversationRepository:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def create(
        self, *, organization_id: int, chatbot_id: int, user_id: int, title: str
    ) -> Conversation:
        conversation = Conversation(
            organization_id=organization_id,
            chatbot_id=chatbot_id,
            user_id=user_id,
            title=title,
        )
        self.db.add(conversation)
        return conversation

    async def get_by_id_for_organization(
        self, organization_id: int, conversation_id: int
    ) -> Conversation | None:
        result = await self.db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_organization(
        self,
        organization_id: int,
        *,
        chatbot_id: int | None = None,
        user_id: int | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[Conversation], int]:
        conditions = [Conversation.organization_id == organization_id]
        if chatbot_id is not None:
            conditions.append(Conversation.chatbot_id == chatbot_id)
        if user_id is not None:
            conditions.append(Conversation.user_id == user_id)

        total = await self.db.scalar(
            select(func.count()).select_from(Conversation).where(*conditions)
        )
        result = await self.db.execute(
            select(Conversation)
            .where(*conditions)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total or 0
