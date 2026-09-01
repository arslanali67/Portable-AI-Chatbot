"""Public widget endpoints — anonymous sessions + SSE chat.

Thin public boundary. Server derives org/chatbot from public_key/session;
client never supplies them.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.core.rate_limit import widget_ip_rate_limiter, widget_rate_limiter
from app.models import Chatbot, Conversation, WidgetConfig, WidgetSession
from app.schemas.public_widget import (
    WidgetChatRequest,
    WidgetConfigResponse,
    WidgetSessionRequest,
    WidgetSessionResponse,
)
from app.services.chat_runtime import (
    ChatRuntimeService,
    RuntimeErrorAI,
)
from app.services.public_widget import (
    InvalidSessionError,
    OriginDeniedError,
    PublicChatbotUnavailableError,
    PublicWidgetService,
    WidgetError,
)

router = APIRouter(prefix="/public/widget", tags=["public-widget"])
logger = get_logger("portableai.public_widget")


def _widget_error(exc: WidgetError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _build_config_response(chatbot: Chatbot, config: WidgetConfig) -> WidgetConfigResponse:
    """The entire public-response safety boundary: explicit field allowlist,
    never a raw model dump. Never system_prompt, provider_id, model_id,
    organization_id, DB ids, credentials."""
    return WidgetConfigResponse(
        chatbot_name=chatbot.name,
        welcome_message=chatbot.welcome_message,
        language=chatbot.language,
        enabled=True,
        theme_color=config.theme_color,
        widget_position=config.widget_position.value if config.widget_position else None,
        avatar_url=config.avatar_url,
    )


@router.get("/config", response_model=WidgetConfigResponse)
async def get_public_config(
    request: Request,
    public_key: str = Query(min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
):
    """Theme/language-only, public_key-derived lookup — no session created,
    no DB write. Fetched eagerly at widget.js script load so the
    always-visible launcher can render themed before the visitor ever
    interacts; the existing lazy session-creation flow below is unchanged."""
    if not widget_ip_rate_limiter.allow(f"ip:{_client_ip(request)}"):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
    try:
        config, chatbot = await PublicWidgetService(db).get_public_config(public_key)
    except PublicChatbotUnavailableError as exc:
        raise _widget_error(exc)
    return _build_config_response(chatbot, config)


@router.post("/session", response_model=WidgetSessionResponse)
async def create_session(
    payload: WidgetSessionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    origin = payload.origin or request.headers.get("origin")
    try:
        session, config, chatbot = await PublicWidgetService(db).create_session(
            payload.public_key, origin
        )
    except PublicChatbotUnavailableError as exc:
        raise _widget_error(exc)
    except OriginDeniedError as exc:
        raise _widget_error(exc)

    return WidgetSessionResponse(
        session_token=session.session_token,
        config=_build_config_response(chatbot, config),
    )


@router.post("/chat/stream")
async def stream_chat(
    payload: WidgetChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    origin = payload.origin or request.headers.get("origin")
    client_ip = request.client.host if request.client else "unknown"
    service = PublicWidgetService(db)

    # Rate limit before any work.
    if not widget_rate_limiter.allow(f"session:{payload.session_token}"):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
    if not widget_ip_rate_limiter.allow(f"ip:{client_ip}"):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")

    async def event_generator():
        try:
            session, config, chatbot = await service.resolve_session(payload.session_token, origin)
            organization_id = chatbot.organization_id
            placeholder_user = await service.get_or_create_placeholder_user(organization_id)

            if session.conversation_id is None:
                conversation = await service.ensure_conversation(
                    organization_id, session.chatbot_id, placeholder_user
                )
                session.conversation_id = conversation.id
                await db.commit()
            else:
                conversation = await db.get(Conversation, session.conversation_id)

            # Defense-in-depth: a widget session may only stream against its
            # own chatbot's conversation. A conversation bound to a different
            # chatbot is refused without leaking any details — never follow it.
            if conversation is None or conversation.chatbot_id != session.chatbot_id:
                yield f"event: error\ndata: {json.dumps({'detail': 'Invalid session'})}\n\n"
                return

            async for event_type, data in ChatRuntimeService(db).stream_turn(
                organization_id, conversation, payload
            ):
                if event_type == "user_message":
                    yield f"event: user\ndata: {json.dumps({'content': data.content})}\n\n"
                elif event_type == "start":
                    yield f"event: start\ndata: {json.dumps(data)}\n\n"
                elif event_type == "token":
                    yield f"event: token\ndata: {json.dumps(data)}\n\n"
                elif event_type == "end":
                    yield f"event: end\ndata: {json.dumps(data)}\n\n"
        except InvalidSessionError as exc:
            yield f"event: error\ndata: {json.dumps({'detail': exc.detail})}\n\n"
        except PublicChatbotUnavailableError as exc:
            yield f"event: error\ndata: {json.dumps({'detail': exc.detail})}\n\n"
        except OriginDeniedError as exc:
            yield f"event: error\ndata: {json.dumps({'detail': exc.detail})}\n\n"
        except RuntimeErrorAI as exc:
            yield f"event: error\ndata: {json.dumps({'detail': exc.detail})}\n\n"
        except Exception:  # noqa: BLE001 - safe boundary
            logger.exception("Unhandled error in widget chat stream")
            yield f"event: error\ndata: {json.dumps({'detail': 'Streaming failed'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
