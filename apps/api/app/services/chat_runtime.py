"""Chat runtime service — one chat turn orchestration.

Flow: authz chain → save user message (commit) → ordered history →
AIRequest from chatbot config → AIGateway (outside DB transaction) →
save assistant message (commit) → response DTO.

Never calls providers directly; always via AIGateway.

Structured output (chatbot.response_schema set): exactly one extra gateway
call may be made — a single retry, with the validation error fed back to
the model as corrective feedback, if the first response doesn't validate.
A chatbot with response_schema=NULL is completely unaffected: one gateway
call, unchanged from pre-milestone behavior. See _generate_structured().

Tool calling (chatbot.tools set) is surface-only: the platform never
executes a tool. It's always exactly one gateway call — a tool-call
request from the model is the terminal output of the turn, persisted as
an ordinary ASSISTANT message (human-readable content summary; raw
tool-call data in metadata). No second call, no auto-continuation, no
tool-result message type.
"""

import json
from dataclasses import replace

import jsonschema
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.contracts import AIMessage, AIMessageRole, AIRequest, AIResponse
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

    async def _generate_structured(
        self, request: AIRequest, response_schema: dict, credential_override: str | None
    ) -> AIResponse:
        """Schema-validated generation: one gateway call, and — only if that
        response fails validation — exactly one retry with the validation
        error appended as corrective feedback. Raises AIInvalidRequestError
        (the existing adapter-boundary 502-class error) if the retry is also
        invalid; never returns or lets the caller persist invalid content."""
        structured_request = replace(request, response_schema=response_schema)

        response = await gateway.generate(structured_request, credential_override=credential_override)
        error = self._schema_validation_error(response.content, response_schema)
        if error is None:
            return response

        # Feedback as an ordinary USER-role message — matches the existing
        # precedent for injecting non-human context (ContextBuilder's RAG
        # context is also appended as a USER message, not SYSTEM); there is
        # no TOOL role in this codebase and none is being added here.
        retry_messages = list(structured_request.messages) + [
            AIMessage(role=AIMessageRole.ASSISTANT, content=response.content),
            AIMessage(
                role=AIMessageRole.USER,
                content=(
                    "Your previous response did not satisfy the required JSON schema: "
                    f"{error}. Respond again with ONLY valid JSON matching the schema, "
                    "no other text."
                ),
            ),
        ]
        retry_request = replace(structured_request, messages=retry_messages)
        retry_response = await gateway.generate(retry_request, credential_override=credential_override)
        retry_error = self._schema_validation_error(retry_response.content, response_schema)
        if retry_error is None:
            return retry_response

        raise AIInvalidRequestError(
            f"model response did not match the configured schema after one retry: {retry_error}"
        )

    @staticmethod
    def _schema_validation_error(content: str, schema: dict) -> str | None:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            return f"response is not valid JSON: {exc}"
        try:
            jsonschema.validate(parsed, schema)
        except jsonschema.exceptions.ValidationError as exc:
            return exc.message
        except jsonschema.exceptions.SchemaError as exc:
            return f"configured schema is invalid: {exc.message}"
        return None

    @staticmethod
    def _persisted_content_and_tool_calls(response: AIResponse) -> tuple[str, list[dict] | None]:
        """When the model made tool call(s) instead of answering directly,
        persisted `content` becomes a human-readable summary (so the
        existing chat bubble stays meaningful with zero frontend changes)
        and the raw tool-call data (id, name, unparsed arguments string) is
        returned separately for the message's metadata column. Otherwise
        content passes through unchanged and there's no tool-call metadata."""
        if not response.tool_calls:
            return response.content, None
        summary = "; ".join(
            f"Requested tool call: {tc.name}({tc.arguments})" for tc in response.tool_calls
        )
        tool_calls_meta = [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in response.tool_calls
        ]
        return summary, tool_calls_meta

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
        if chatbot.tools:
            request = replace(request, tools=chatbot.tools)

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
            if chatbot.response_schema is not None:
                response = await self._generate_structured(
                    request, chatbot.response_schema, byok_key
                )
            else:
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
        content, tool_calls_meta = self._persisted_content_and_tool_calls(response)
        message_metadata = {
            "provider_id": response.provider_id,
            "model_id": response.model_id,
            "finish_reason": response.finish_reason,
        }
        if tool_calls_meta is not None:
            message_metadata["tool_calls"] = tool_calls_meta
        assistant_sequence = (await self.messages.get_latest_sequence(conversation_id)) + 1
        assistant_message = await self.messages.create(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=content,
            sequence_number=assistant_sequence,
            metadata=message_metadata,
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
        if chatbot.tools:
            request = replace(request, tools=chatbot.tools)

        # 3. Stream via gateway, assemble final content.
        yield ("start", {"provider_id": request.provider_id, "model_id": request.model_id})
        chunks: list[str] = []
        finish_reason = "stop"
        turn_tool_calls_meta: list[dict] | None = None
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
            if chatbot.response_schema is not None or chatbot.tools:
                # Both structured output (schema validation needs the
                # complete response before it can be judged valid) and tool
                # calling (a tool-call request only exists once the response
                # is fully assembled) share the same buffered fallback: a
                # single non-streaming AIGateway.generate call, emitting one
                # "token" + "end" SSE pair instead of true incremental
                # streaming. The SSE event shape is unchanged either way, so
                # the frontend needs no changes.
                if chatbot.response_schema is not None:
                    buffered_response = await self._generate_structured(
                        request, chatbot.response_schema, byok_key
                    )
                else:
                    buffered_response = await gateway.generate(
                        request, credential_override=byok_key
                    )
                content, turn_tool_calls_meta = self._persisted_content_and_tool_calls(
                    buffered_response
                )
                chunks.append(content)
                yield ("token", {"delta": content})
                finish_reason = buffered_response.finish_reason
            else:
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
        stream_metadata = {
            "provider_id": request.provider_id,
            "model_id": request.model_id,
            "finish_reason": finish_reason,
        }
        if turn_tool_calls_meta is not None:
            stream_metadata["tool_calls"] = turn_tool_calls_meta
        assistant_sequence = (await self.messages.get_latest_sequence(conversation_id)) + 1
        assistant_message = await self.messages.create(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content="".join(chunks),
            sequence_number=assistant_sequence,
            metadata=stream_metadata,
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
