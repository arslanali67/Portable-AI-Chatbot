"""Message service — create user messages, list history. Immutable."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message, User
from app.models.enums import ConversationStatus, MessageRole
from app.repositories.conversation import ConversationRepository
from app.repositories.message import MessageRepository
from app.schemas.conversation import MessageCreate, MAX_LIST_LIMIT


class ConversationNotFoundError(Exception):
    pass


class ConversationArchivedError(Exception):
    pass


class SequenceConflictError(Exception):
    pass


class MessageService:
    def __init__(self, db_session: AsyncSession):
        self.conversations = ConversationRepository(db_session)
        self.messages = MessageRepository(db_session)

    async def create_user_message(
        self, organization_id: int, conversation_id: int, payload: MessageCreate
    ) -> Message:
        conversation = await self.conversations.get_by_id_for_organization(
            organization_id, conversation_id
        )
        if conversation is None:
            raise ConversationNotFoundError()
        if conversation.status != ConversationStatus.ACTIVE:
            raise ConversationArchivedError()

        sequence = (await self.messages.get_latest_sequence(conversation_id)) + 1
        message = await self.messages.create(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=payload.content,
            sequence_number=sequence,
            metadata=payload.metadata,
        )
        try:
            await self.messages.db.commit()
        except IntegrityError as exc:
            await self.messages.db.rollback()
            if "uq_message_conversation_sequence" in str(exc.orig):
                raise SequenceConflictError() from exc
            raise
        await self.messages.db.refresh(message)
        return message

    async def list_messages(
        self, organization_id: int, conversation_id: int, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[Message], int]:
        conversation = await self.conversations.get_by_id_for_organization(
            organization_id, conversation_id
        )
        if conversation is None:
            raise ConversationNotFoundError()
        limit = min(max(limit, 1), MAX_LIST_LIMIT)
        offset = max(offset, 0)
        return await self.messages.list_for_conversation(
            conversation_id, limit=limit, offset=offset
        )
