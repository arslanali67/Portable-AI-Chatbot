"""Chat runtime service — one chat turn orchestration.

Flow: authz chain → save user message (commit) → ordered history →
AIRequest from chatbot config → AIGateway (outside DB transaction) →
save assistant message (commit) → response DTO.

Never calls providers directly; always via AIGateway.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.contracts import AIMessage, AIMessageRole, AIRequest
from app.ai.exceptions import (
    AIAuthenticationError,
    AICapabilityNotSupportedError,
    AIError,
    AIInvalidRequestError,
    AIModelNotFoundError,
    AIProviderError,
    AIProviderUnavailableError,
    AIRateLimitError,
)
from app.ai.registry import gateway, model_registry, provider_registry
from app.core.config import settings
from app.models import Chatbot, Conversation, Message, User
from app.models.enums import ConversationStatus, MembershipRole, MessageRole
from app.repositories.chatbot import ChatbotRepository
from app.repositories.conversation import ConversationRepository
from app.repositories.membership import MembershipRepository
from app.repositories.message import MessageRepository
from app.schemas.chat_runtime import ChatRequest, ChatResponse
from app.schemas.knowledge import RetrievedChunkResponse
from app.services.ai_provider_credential import AIProviderCredentialService
from app.services.ai_provider_override import AIProviderOverrideService
from app.services.context_builder import ContextBuilder
from app.services.retrieval import (
    ChatbotNotFoundError as RetrievalChatbotNotFoundError,
    RetrievalService,
)


class ConversationNotFoundError(Exception):
    pass


class ConversationArchivedError(Exception):
    pass


class AccessDeniedError(Exception):
    pass


class RuntimeErrorAI(Exception):
    """Provider-neutral runtime failure wrapper.

    Carries an HTTP status; message is safe to expose (no provider internals).
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class ChatRuntimeService:
    def __init__(self, db_session: AsyncSession):
        self.conversations = ConversationRepository(db_session)
        self.chatbots = ChatbotRepository(db_session)
        self.memberships = MembershipRepository(db_session)
        self.messages = MessageRepository(db_session)

    async def _retrieve(
        self, organization_id: int, chatbot: Chatbot, chatbot_id: int, query: str
    ) -> tuple[list[RetrievedChunkResponse], int]:
        """Per-chatbot RAG: skip RetrievalService entirely when disabled;
        otherwise resolve top_k (chatbot override, else global default)."""
        top_k = chatbot.rag_top_k if chatbot.rag_top_k is not None else settings.rag_top_k
        if not chatbot.rag_enabled:
            return [], top_k
        try:
            retrieved = await RetrievalService(self.messages.db).search(
                organization_id, chatbot_id, query, top_k
            )
        except RetrievalChatbotNotFoundError as exc:
            raise RuntimeErrorAI(500, "Chatbot configuration not found") from exc
        except Exception as exc:  # noqa: BLE001 - retrieval boundary
            raise RuntimeErrorAI(500, "Knowledge retrieval failed") from exc
        return retrieved, top_k

    async def chat(
        self,
        user: User,
        organization_id: int,
        conversation_id: int,
        payload: ChatRequest,
    ) -> ChatResponse:
        conversation = await self._authorize(user, organization_id, conversation_id)
        chatbot = await self.chatbots.get_by_id_for_organization(
            organization_id, conversation.chatbot_id
        )
        if chatbot is None:
            raise RuntimeErrorAI(500, "Chatbot configuration not found")

        # 1. Save user message, commit.
        sequence = (await self.messages.get_latest_sequence(conversation_id)) + 1
        user_message = await self.messages.create(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=payload.content,
            sequence_number=sequence,
        )
        await self.messages.db.commit()
        await self.messages.db.refresh(user_message)

        # 2. Build request from trusted resources (chatbot config + history
        # + RAG context via RetrievalService + ContextBuilder).
        history = await self._history_for_gateway(conversation_id)
        chatbot_id = conversation.chatbot_id
        retrieved, effective_top_k = await self._retrieve(
            organization_id, chatbot, chatbot_id, payload.content
        )

        request = ContextBuilder(top_k=effective_top_k).build(
            provider_id=chatbot.provider_id,
            model_id=chatbot.model_id,
            system_prompt=chatbot.system_prompt or None,
            history=history,
            retrieved=retrieved,
            latest_user_content=payload.content,
        )

        # 3. Call AI outside the DB transaction.
        try:
            overrides = AIProviderOverrideService(self.messages.db)
            if await overrides.is_provider_disabled(chatbot.provider_id):
                raise AIProviderUnavailableError(
                    f"provider disabled by admin: {chatbot.provider_id}"
                )
            if await overrides.is_model_disabled(chatbot.provider_id, chatbot.model_id):
                raise AIModelNotFoundError(f"model disabled by admin: {chatbot.model_id}")
            credentials = AIProviderCredentialService(
                self.messages.db, provider_registry, model_registry
            )
            byok_key = await credentials.resolve_decrypted(organization_id, chatbot.provider_id)
            response = await gateway.generate(request, credential_override=byok_key)
        except AIProviderUnavailableError as exc:
            raise RuntimeErrorAI(502, "AI provider unavailable") from exc
        except AIAuthenticationError as exc:
            raise RuntimeErrorAI(502, "AI provider authentication failed") from exc
        except AIRateLimitError as exc:
            raise RuntimeErrorAI(429, "AI provider rate limit exceeded") from exc
        except (AIInvalidRequestError, AIModelNotFoundError, AICapabilityNotSupportedError) as exc:
            raise RuntimeErrorAI(502, "AI request could not be fulfilled") from exc
        except AIProviderError as exc:
            raise RuntimeErrorAI(502, "AI provider error") from exc
        except AIError as exc:
            raise RuntimeErrorAI(500, "AI processing failed") from exc

        # 4. Save assistant message, commit.
        assistant_sequence = (await self.messages.get_latest_sequence(conversation_id)) + 1
        assistant_message = await self.messages.create(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=response.content,
            sequence_number=assistant_sequence,
            metadata={
                "provider_id": response.provider_id,
                "model_id": response.model_id,
                "finish_reason": response.finish_reason,
            },
        )
        await self.messages.db.commit()
        await self.messages.db.refresh(assistant_message)

        return ChatResponse(
            conversation_id=conversation_id,
            user_message=user_message,
            assistant_message=assistant_message,
        )

    async def stream_chat(
        self,
        user: User,
        organization_id: int,
        conversation_id: int,
        payload: ChatRequest,
    ):
        """Streaming chat turn. Yields (event_type, data) tuples; caller maps
        to SSE. Persists user message before streaming, assistant after."""
        conversation = await self._authorize(user, organization_id, conversation_id)
        async for item in self.stream_turn(organization_id, conversation, payload):
            yield item

    async def stream_turn(self, organization_id: int, conversation: Conversation, payload: ChatRequest):
        """Shared streaming turn used by authenticated and public paths.
        Caller must have already authorized the conversation."""
        chatbot = await self.chatbots.get_by_id_for_organization(
            organization_id, conversation.chatbot_id
        )
        if chatbot is None:
            raise RuntimeErrorAI(500, "Chatbot configuration not found")

        conversation_id = conversation.id
        # 1. Save user message, commit (existing strategy).
        sequence = (await self.messages.get_latest_sequence(conversation_id)) + 1
        user_message = await self.messages.create(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=payload.content,
            sequence_number=sequence,
        )
        await self.messages.db.commit()
        await self.messages.db.refresh(user_message)
        yield ("user_message", user_message)

        # 2. History + RAG + ContextBuilder (same pipeline as normal chat).
        history = await self._history_for_gateway(conversation_id)
        chatbot_id = conversation.chatbot_id
        retrieved, effective_top_k = await self._retrieve(
            organization_id, chatbot, chatbot_id, payload.content
        )

        request = ContextBuilder(top_k=effective_top_k).build(
            provider_id=chatbot.provider_id,
            model_id=chatbot.model_id,
            system_prompt=chatbot.system_prompt or None,
            history=history,
            retrieved=retrieved,
            latest_user_content=payload.content,
        )

        # 3. Stream via gateway, assemble final content.
        yield ("start", {"provider_id": request.provider_id, "model_id": request.model_id})
        chunks: list[str] = []
        finish_reason = "stop"
        try:
            overrides = AIProviderOverrideService(self.messages.db)
            if await overrides.is_provider_disabled(chatbot.provider_id):
                raise AIProviderUnavailableError(
                    f"provider disabled by admin: {chatbot.provider_id}"
                )
            if await overrides.is_model_disabled(chatbot.provider_id, chatbot.model_id):
                raise AIModelNotFoundError(f"model disabled by admin: {chatbot.model_id}")
            credentials = AIProviderCredentialService(
                self.messages.db, provider_registry, model_registry
            )
            byok_key = await credentials.resolve_decrypted(organization_id, chatbot.provider_id)
            async for event in gateway.stream(request, credential_override=byok_key):
                if event.type.value == "token":
                    delta = event.data.get("delta", "")
                    chunks.append(delta)
                    yield ("token", {"delta": delta})
                elif event.type.value == "end":
                    finish_reason = event.data.get("finish_reason", "stop")
        except AIProviderUnavailableError as exc:
            raise RuntimeErrorAI(502, "AI provider unavailable") from exc
        except AIAuthenticationError as exc:
            raise RuntimeErrorAI(502, "AI provider authentication failed") from exc
        except AIRateLimitError as exc:
            raise RuntimeErrorAI(429, "AI provider rate limit exceeded") from exc
        except (AIInvalidRequestError, AIModelNotFoundError, AICapabilityNotSupportedError) as exc:
            raise RuntimeErrorAI(502, "AI request could not be fulfilled") from exc
        except AIProviderError as exc:
            raise RuntimeErrorAI(502, "AI provider error") from exc
        except AIError as exc:
            raise RuntimeErrorAI(500, "AI processing failed") from exc

        # 4. Persist ONE assistant message.
        assistant_sequence = (await self.messages.get_latest_sequence(conversation_id)) + 1
        assistant_message = await self.messages.create(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content="".join(chunks),
            sequence_number=assistant_sequence,
            metadata={
                "provider_id": request.provider_id,
                "model_id": request.model_id,
                "finish_reason": finish_reason,
            },
        )
        await self.messages.db.commit()
        await self.messages.db.refresh(assistant_message)
        yield ("end", {"message_id": assistant_message.id, "sequence_number": assistant_message.sequence_number})

    async def _authorize(
        self, user: User, organization_id: int, conversation_id: int
    ) -> Conversation:
        conversation = await self.conversations.get_by_id_for_organization(
            organization_id, conversation_id
        )
        if conversation is None:
            raise ConversationNotFoundError()

        if conversation.status != ConversationStatus.ACTIVE:
            raise ConversationArchivedError()

        membership = await self.memberships.get(user.id, organization_id)
        if membership is None:
            raise AccessDeniedError()
        if (
            membership.role not in (MembershipRole.OWNER, MembershipRole.ADMIN)
            and conversation.user_id != user.id
        ):
            raise AccessDeniedError()
        return conversation

    async def _history_for_gateway(self, conversation_id: int) -> list[AIMessage]:
        messages, _ = await self.messages.list_for_conversation(
            conversation_id, limit=200, offset=0
        )
        return [
            AIMessage(
                role=AIMessageRole(m.role.value),
                content=m.content,
            )
            for m in messages
        ]
