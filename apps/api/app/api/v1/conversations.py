"""Conversation endpoints — chatbot-scoped create/list, org-scoped get,
messages, archive. All routes require membership; reads are member-scoped to
own conversations, owner/admin see all.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_organization_role
from app.core.logging import get_logger
from app.models import Membership, User
from app.models.enums import MembershipRole
from app.schemas.conversation import (
    ConversationCreate,
    ConversationListResponse,
    ConversationResponse,
    ConversationUpdate,
    MessageCreate,
    MessageListResponse,
    MessageResponse,
)
from app.schemas.chat_runtime import ChatRequest, ChatResponse, PresetQuestionRequest
from app.services.chat_runtime import (
    AccessDeniedError,
    ChatRuntimeService,
    ConversationArchivedError as RuntimeArchivedError,
    ConversationNotFoundError as RuntimeConvNotFoundError,
    PresetQuestionIndexError,
    RuntimeErrorAI,
)
from app.services.conversation import (
    ArchivePermissionError,
    ChatbotNotFoundError,
    ConversationArchivedError as UpdateArchivedError,
    ConversationNotFoundError,
    ConversationService,
    InvalidArchiveError,
)
from app.services.message import (
    ConversationArchivedError,
    ConversationNotFoundError as MessageConvNotFoundError,
    MessageService,
    SequenceConflictError,
)

router = APIRouter(tags=["conversations"])
logger = get_logger("portableai.conversations")

require_member = Depends(require_organization_role(MembershipRole.MEMBER))


def _conversation_404() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")


# --- Create / list under a chatbot ---


@router.post(
    "/organizations/{organization_id}/chatbots/{chatbot_id}/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    organization_id: int,
    chatbot_id: int,
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    _membership: Membership = require_member,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await ConversationService(db).create(
            current_user, organization_id, chatbot_id, payload
        )
    except ChatbotNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found")


@router.get(
    "/organizations/{organization_id}/chatbots/{chatbot_id}/conversations",
    response_model=ConversationListResponse,
)
async def list_chatbot_conversations(
    organization_id: int,
    chatbot_id: int,
    current_user: User = Depends(get_current_user),
    _membership: Membership = require_member,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    items, total = await ConversationService(db).list(
        organization_id, current_user, chatbot_id=chatbot_id, limit=limit, offset=offset
    )
    return ConversationListResponse(items=items, total=total, limit=limit, offset=offset)


# --- Get single conversation (org-scoped) ---


@router.get(
    "/organizations/{organization_id}/conversations/{conversation_id}",
    response_model=ConversationResponse,
)
async def get_conversation(
    organization_id: int,
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_organization_role(MembershipRole.MEMBER)),
    db: AsyncSession = Depends(get_db),
):
    try:
        conversation = await ConversationService(db).get(organization_id, conversation_id)
    except ConversationNotFoundError:
        raise _conversation_404()
    if (
        membership.role not in (MembershipRole.OWNER, MembershipRole.ADMIN)
        and conversation.user_id != current_user.id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your conversation")
    return conversation


@router.patch(
    "/organizations/{organization_id}/conversations/{conversation_id}",
    response_model=ConversationResponse,
)
async def update_conversation(
    organization_id: int,
    conversation_id: int,
    payload: ConversationUpdate,
    current_user: User = Depends(get_current_user),
    _membership: Membership = require_member,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await ConversationService(db).update(
            current_user, organization_id, conversation_id, payload
        )
    except ConversationNotFoundError:
        raise _conversation_404()
    except ArchivePermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owner/admin may rename others' conversations",
        )
    except UpdateArchivedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conversation is archived")


# --- Messages ---


@router.post(
    "/organizations/{organization_id}/conversations/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_message(
    organization_id: int,
    conversation_id: int,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_organization_role(MembershipRole.MEMBER)),
    db: AsyncSession = Depends(get_db),
):
    try:
        conversation = await ConversationService(db).get(organization_id, conversation_id)
    except ConversationNotFoundError:
        raise _conversation_404()
    if (
        membership.role not in (MembershipRole.OWNER, MembershipRole.ADMIN)
        and conversation.user_id != current_user.id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your conversation")
    try:
        return await MessageService(db).create_user_message(
            organization_id, conversation_id, payload
        )
    except MessageConvNotFoundError:
        raise _conversation_404()
    except ConversationArchivedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conversation is archived")
    except SequenceConflictError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Sequence conflict, retry")


@router.get(
    "/organizations/{organization_id}/conversations/{conversation_id}/messages",
    response_model=MessageListResponse,
)
async def list_messages(
    organization_id: int,
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_organization_role(MembershipRole.MEMBER)),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    try:
        conversation = await ConversationService(db).get(organization_id, conversation_id)
    except ConversationNotFoundError:
        raise _conversation_404()
    if (
        membership.role not in (MembershipRole.OWNER, MembershipRole.ADMIN)
        and conversation.user_id != current_user.id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your conversation")
    items, total = await MessageService(db).list_messages(
        organization_id, conversation_id, limit=limit, offset=offset
    )
    return MessageListResponse(items=items, total=total, limit=limit, offset=offset)


# --- Archive ---


@router.post(
    "/organizations/{organization_id}/conversations/{conversation_id}/archive",
    response_model=ConversationResponse,
)
async def archive_conversation(
    organization_id: int,
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    _membership: Membership = require_member,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await ConversationService(db).archive(
            current_user, organization_id, conversation_id
        )
    except ConversationNotFoundError:
        raise _conversation_404()
    except ArchivePermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owner/admin may archive others' conversations",
        )
    except InvalidArchiveError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conversation is not active")


# --- Chat runtime ---


@router.post(
    "/organizations/{organization_id}/conversations/{conversation_id}/chat",
    response_model=ChatResponse,
)
async def chat_with_conversation(
    organization_id: int,
    conversation_id: int,
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    _membership: Membership = require_member,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await ChatRuntimeService(db).chat(
            current_user, organization_id, conversation_id, payload
        )
    except RuntimeConvNotFoundError:
        raise _conversation_404()
    except RuntimeArchivedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conversation is archived")
    except AccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your conversation")
    except RuntimeErrorAI as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


# --- Preset/FAQ questions (canned response, zero AI Gateway call) ---


@router.post(
    "/organizations/{organization_id}/conversations/{conversation_id}/faq",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def answer_preset_question(
    organization_id: int,
    conversation_id: int,
    payload: PresetQuestionRequest,
    current_user: User = Depends(get_current_user),
    _membership: Membership = require_member,
    db: AsyncSession = Depends(get_db),
):
    try:
        await ChatRuntimeService(db).answer_preset_question_for_conversation(
            current_user, organization_id, conversation_id, payload.question_index
        )
    except RuntimeConvNotFoundError:
        raise _conversation_404()
    except RuntimeArchivedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conversation is archived")
    except AccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your conversation")
    except PresetQuestionIndexError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid question index")
    except RuntimeErrorAI as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


# --- Streaming chat (SSE) ---


@router.post(
    "/organizations/{organization_id}/conversations/{conversation_id}/chat/stream",
)
async def stream_chat_with_conversation(
    organization_id: int,
    conversation_id: int,
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    _membership: Membership = require_member,
    db: AsyncSession = Depends(get_db),
):
    async def event_generator():
        try:
            async for event_type, data in ChatRuntimeService(db).stream_chat(
                current_user, organization_id, conversation_id, payload
            ):
                if event_type == "user_message":
                    yield f"event: start\ndata: {json.dumps({'conversation_id': conversation_id})}\n\n"
                    yield f"event: user\ndata: {json.dumps({'id': data.id, 'content': data.content, 'sequence_number': data.sequence_number})}\n\n"
                elif event_type == "start":
                    yield f"event: start\ndata: {json.dumps(data)}\n\n"
                elif event_type == "token":
                    yield f"event: token\ndata: {json.dumps(data)}\n\n"
                elif event_type == "end":
                    yield f"event: end\ndata: {json.dumps(data)}\n\n"
        except RuntimeConvNotFoundError:
            yield f"event: error\ndata: {json.dumps({'detail': 'Conversation not found'})}\n\n"
        except RuntimeArchivedError:
            yield f"event: error\ndata: {json.dumps({'detail': 'Conversation is archived'})}\n\n"
        except AccessDeniedError:
            yield f"event: error\ndata: {json.dumps({'detail': 'Not your conversation'})}\n\n"
        except RuntimeErrorAI as exc:
            yield f"event: error\ndata: {json.dumps({'detail': exc.detail})}\n\n"
        except Exception:  # noqa: BLE001 - safe boundary
            logger.exception("Unhandled error in conversation chat stream")
            yield f"event: error\ndata: {json.dumps({'detail': 'Streaming failed'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
