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

Tool calling (chatbot.tools set): when chatbot.response_schema is ALSO set,
tool calls stay surface-only (see _generate_structured — unchanged, exact
pre-milestone behavior for that combination). Otherwise, a tool-call
request is executed for real via _run_with_tool_execution(): the platform
runs the registered tool, feeds the result back to the model, and repeats
up to a small bounded number of iterations until the model returns a final
text response (or the cap forces one). Intermediate tool-call/tool-result
exchanges are ephemeral (in-memory AIMessage objects only); only the
turn's final text answer is persisted as one ASSISTANT message, with a
full tool_execution_trace riding in its metadata. See
_run_with_tool_execution() and architecture.md's "Tool Execution
(Platform-Defined Allowlist)".
"""

import asyncio
import json
from dataclasses import replace

import jsonschema
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.contracts import AIMessage, AIMessageRole, AIRequest, AIResponse, AIToolCall
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
from app.ai.registry import gateway, model_registry, provider_registry, tool_registry
from app.ai.tools.base import ToolExecutionError
from app.core.config import settings
from app.core.logging import get_logger
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

logger = get_logger("portableai.chat_runtime")

# Tool execution loop: bounded total gateway calls per turn (1 original +
# up to 4 tool-round-trips). The final permitted call omits `tools`
# entirely, structurally forcing a text-only answer rather than failing
# the turn when the cap is reached.
_MAX_TOOL_ITERATIONS = 5


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

    async def _run_with_tool_execution(
        self,
        request: AIRequest,
        credential_override: str | None,
        *,
        organization_id: int,
        chatbot_id: int,
    ) -> tuple[AIResponse, list[dict]]:
        """Executes registered tools the model requests, feeding results
        back and re-calling the model, until it returns a final text
        response (no more tool calls) or _MAX_TOOL_ITERATIONS is reached.
        On the final permitted iteration, `tools` is omitted from the
        request entirely, structurally forcing a text-only answer rather
        than failing the turn. Intermediate tool-call/tool-result
        exchanges are ephemeral (in-memory AIMessage objects only) — never
        persisted to the messages table; the caller persists only the
        final response, with the returned trace riding in its metadata.
        Only called when chatbot.tools is set and chatbot.response_schema
        is NOT set — see chat()/stream_turn()."""
        messages = list(request.messages)
        trace: list[dict] = []
        current_request = request

        for iteration in range(1, _MAX_TOOL_ITERATIONS + 1):
            is_final_attempt = iteration == _MAX_TOOL_ITERATIONS
            if is_final_attempt:
                current_request = replace(current_request, tools=None)

            response = await gateway.generate(current_request, credential_override=credential_override)

            if not response.tool_calls or is_final_attempt:
                return response, trace

            messages.append(
                AIMessage(
                    role=AIMessageRole.ASSISTANT,
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )
            for tool_call in response.tool_calls:
                result = await self._execute_tool(
                    tool_call, organization_id=organization_id, chatbot_id=chatbot_id
                )
                trace.append(
                    {
                        "iteration": iteration,
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                        "result": result,
                    }
                )
                messages.append(
                    AIMessage(role=AIMessageRole.TOOL, content=result, tool_call_id=tool_call.id)
                )
            current_request = replace(current_request, messages=messages)

        # Unreachable: every iteration either returns (a non-tool-call
        # response, or the forced final attempt) before reaching here.
        raise AssertionError("tool execution loop exited without a response")  # pragma: no cover

    async def _execute_tool(
        self, tool_call: AIToolCall, *, organization_id: int, chatbot_id: int
    ) -> str:
        """Runs one tool call and always returns a string result — never
        raises. An unknown tool, invalid/unparseable arguments, an
        expected ToolExecutionError, a timeout, or any other unexpected
        exception all become a clean, generic error-shaped result fed
        back to the model — never a raw traceback, never logged with
        sensitive detail, never a whole-turn failure."""
        tool = tool_registry.get(tool_call.name)
        if tool is None:
            return json.dumps({"error": f"unknown tool: {tool_call.name}"})

        try:
            arguments = json.loads(tool_call.arguments) if tool_call.arguments else {}
            if not isinstance(arguments, dict):
                raise ToolExecutionError("tool arguments must be a JSON object")
        except json.JSONDecodeError:
            return json.dumps({"error": "invalid tool arguments: not valid JSON"})

        try:
            result = await asyncio.wait_for(
                tool.execute(
                    arguments,
                    organization_id=organization_id,
                    chatbot_id=chatbot_id,
                    db_session=self.messages.db,
                ),
                timeout=settings.tool_execution_timeout_seconds,
            )
            return result
        except ToolExecutionError as exc:
            return json.dumps({"error": str(exc)})
        except asyncio.TimeoutError:
            return json.dumps({"error": "tool execution timed out"})
        except Exception:  # noqa: BLE001 - never leak internals to the model or logs
            logger.warning(
                "tool execution failed unexpectedly (name=%s, chatbot_id=%s)",
                tool_call.name,
                chatbot_id,
            )
            return json.dumps({"error": "tool execution failed"})

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
            tool_trace: list[dict] | None = None
            if chatbot.response_schema is not None:
                # Mutual exclusion with real execution: tools stay
                # surface-only/unexecuted here, exact pre-milestone
                # behavior for this combination — unchanged.
                response = await self._generate_structured(
                    request, chatbot.response_schema, byok_key
                )
            elif chatbot.tools:
                response, tool_trace = await self._run_with_tool_execution(
                    request, byok_key, organization_id=organization_id, chatbot_id=chatbot_id
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
        if tool_trace:
            message_metadata["tool_execution_trace"] = tool_trace
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
        turn_tool_trace: list[dict] | None = None
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
                # Both structured output and tool calling share the same
                # buffered fallback — one or more non-streaming
                # AIGateway.generate calls (a single call for structured
                # output; possibly several for tool execution's internal
                # loop), emitting exactly one "token" + "end" SSE pair
                # regardless of how many internal calls happened. The SSE
                # event shape is unchanged either way, so the frontend
                # needs no changes.
                if chatbot.response_schema is not None:
                    # Mutual exclusion with real execution: tools stay
                    # surface-only/unexecuted here, exact pre-milestone
                    # behavior for this combination — unchanged. (The
                    # outer `if` above guarantees chatbot.tools is truthy
                    # whenever this is False, so no trailing `else` is
                    # needed.)
                    buffered_response = await self._generate_structured(
                        request, chatbot.response_schema, byok_key
                    )
                else:
                    buffered_response, turn_tool_trace = await self._run_with_tool_execution(
                        request,
                        byok_key,
                        organization_id=organization_id,
                        chatbot_id=chatbot_id,
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
        if turn_tool_trace:
            stream_metadata["tool_execution_trace"] = turn_tool_trace
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
