"""Conversation service — creation, listing, archive. Tenant-scoped."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chatbot, Conversation, User
from app.models.enums import ConversationStatus, MembershipRole
from app.repositories.chatbot import ChatbotRepository
from app.repositories.conversation import ConversationRepository
from app.repositories.membership import MembershipRepository
from app.schemas.conversation import ConversationCreate, MAX_LIST_LIMIT


class ConversationNotFoundError(Exception):
    pass


class ChatbotNotFoundError(Exception):
    pass


class InvalidArchiveError(Exception):
    pass


class ArchivePermissionError(Exception):
    pass


class ConversationService:
    def __init__(self, db_session: AsyncSession):
        self.conversations = ConversationRepository(db_session)
        self.chatbots = ChatbotRepository(db_session)
        self.memberships = MembershipRepository(db_session)

    async def create(self, user: User, organization_id: int, chatbot_id: int, payload: ConversationCreate) -> Conversation:
        chatbot = await self.chatbots.get_by_id_for_organization(organization_id, chatbot_id)
        if chatbot is None:
            raise ChatbotNotFoundError()
        conversation = await self.conversations.create(
            organization_id=organization_id,
            chatbot_id=chatbot_id,
            user_id=user.id,
            title=payload.title,
        )
        await self.conversations.db.commit()
        await self.conversations.db.refresh(conversation)
        return conversation

    async def get(self, organization_id: int, conversation_id: int) -> Conversation:
        conversation = await self.conversations.get_by_id_for_organization(
            organization_id, conversation_id
        )
        if conversation is None:
            raise ConversationNotFoundError()
        return conversation

    async def list(
        self,
        organization_id: int,
        user: User,
        *,
        chatbot_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Conversation], int]:
        limit = min(max(limit, 1), MAX_LIST_LIMIT)
        offset = max(offset, 0)

        membership = await self.memberships.get(user.id, organization_id)
        is_owner_or_admin = (
            membership is not None
            and membership.role in (MembershipRole.OWNER, MembershipRole.ADMIN)
        )
        # owner/admin → all org conversations; member → own conversations only.
        scope_user_id = None if is_owner_or_admin else user.id
        return await self.conversations.list_for_organization(
            organization_id,
            chatbot_id=chatbot_id,
            user_id=scope_user_id,
            limit=limit,
            offset=offset,
        )

    async def archive(self, user: User, organization_id: int, conversation_id: int) -> Conversation:
        conversation = await self.get(organization_id, conversation_id)

        membership = await self.memberships.get(user.id, organization_id)
        is_owner_or_admin = (
            membership is not None
            and membership.role in (MembershipRole.OWNER, MembershipRole.ADMIN)
        )
        if not is_owner_or_admin and conversation.user_id != user.id:
            raise ArchivePermissionError()

        if conversation.status != ConversationStatus.ACTIVE:
            raise InvalidArchiveError("conversation is not active")

        conversation.status = ConversationStatus.ARCHIVED
        await self.conversations.db.commit()
        await self.conversations.db.refresh(conversation)
        return conversation
