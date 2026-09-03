"""Chatbot endpoints — organization-scoped CRUD + lifecycle.

Authorization: authenticated, org membership, role check, chatbot belongs to org.
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_organization_role
from app.models import Chatbot, Membership
from app.models.enums import MembershipRole
from app.schemas.chatbot import ChatbotCreate, ChatbotResponse, ChatbotUpdate
from app.schemas.widget_config import (
    WidgetConfigAdminResponse,
    WidgetConfigCreate,
    WidgetConfigUpdate,
)
from app.services.chatbot import (
    ChatbotNotFoundError,
    ChatbotService,
    DuplicateSlugError,
    InvalidProviderModelError,
    InvalidStatusTransitionError,
    InvalidToolError,
)
from app.services.widget_config import (
    ImageTooLargeError,
    InvalidImageError,
    WidgetConfigNotFoundError,
    WidgetConfigService,
)

router = APIRouter(prefix="/organizations/{organization_id}/chatbots", tags=["chatbots"])


@router.post("", response_model=ChatbotResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_organization_role(MembershipRole.ADMIN))])
async def create_chatbot(
    organization_id: int,
    payload: ChatbotCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        chatbot = await ChatbotService(db).create(organization_id, payload)
    except DuplicateSlugError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Slug already taken in this organization",
        )
    except InvalidProviderModelError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.detail)
    except InvalidToolError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.detail)
    return chatbot


@router.get("", response_model=list[ChatbotResponse], dependencies=[Depends(get_current_user)])
async def list_chatbots(
    organization_id: int,
    _membership: Membership = Depends(require_organization_role(MembershipRole.MEMBER)),
    db: AsyncSession = Depends(get_db),
):
    return await ChatbotService(db).list(organization_id)


@router.get("/{chatbot_id}", response_model=ChatbotResponse,
            dependencies=[Depends(get_current_user)])
async def get_chatbot(
    organization_id: int,
    chatbot_id: int,
    _membership: Membership = Depends(require_organization_role(MembershipRole.MEMBER)),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await ChatbotService(db).get(organization_id, chatbot_id)
    except ChatbotNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found")


@router.patch("/{chatbot_id}", response_model=ChatbotResponse)
async def update_chatbot(
    organization_id: int,
    chatbot_id: int,
    payload: ChatbotUpdate,
    _membership: Membership = Depends(require_organization_role(MembershipRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await ChatbotService(db).update(organization_id, chatbot_id, payload)
    except ChatbotNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found")
    except DuplicateSlugError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Slug already taken in this organization",
        )
    except InvalidProviderModelError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.detail)
    except InvalidToolError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.detail)


@router.post("/{chatbot_id}/activate", response_model=ChatbotResponse)
async def activate_chatbot(
    organization_id: int,
    chatbot_id: int,
    _membership: Membership = Depends(require_organization_role(MembershipRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await ChatbotService(db).activate(organization_id, chatbot_id)
    except ChatbotNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found")
    except InvalidStatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/{chatbot_id}/archive", response_model=ChatbotResponse)
async def archive_chatbot(
    organization_id: int,
    chatbot_id: int,
    _membership: Membership = Depends(require_organization_role(MembershipRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await ChatbotService(db).archive(organization_id, chatbot_id)
    except ChatbotNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found")
    except InvalidStatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


async def _get_chatbot_or_404(db: AsyncSession, organization_id: int, chatbot_id: int) -> None:
    try:
        await ChatbotService(db).get(organization_id, chatbot_id)
    except ChatbotNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found")


@router.post(
    "/{chatbot_id}/widget-config",
    response_model=WidgetConfigAdminResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_widget_config(
    organization_id: int,
    chatbot_id: int,
    payload: WidgetConfigCreate = WidgetConfigCreate(),
    _membership: Membership = Depends(require_organization_role(MembershipRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Create a public widget credential for a chatbot (admin+)."""
    await _get_chatbot_or_404(db, organization_id, chatbot_id)
    config = await WidgetConfigService(db).create(
        chatbot_id,
        allowed_origins=payload.allowed_origins,
        theme_color=payload.theme_color,
        widget_position=payload.widget_position,
    )
    return config


@router.patch("/{chatbot_id}/widget-config", response_model=WidgetConfigAdminResponse)
async def update_widget_config(
    organization_id: int,
    chatbot_id: int,
    payload: WidgetConfigUpdate,
    _membership: Membership = Depends(require_organization_role(MembershipRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Update theme/position/allowed_origins for an existing widget config
    (admin+). No update path existed before this milestone."""
    await _get_chatbot_or_404(db, organization_id, chatbot_id)
    try:
        config = await WidgetConfigService(db).update(
            chatbot_id, payload.model_dump(exclude_unset=True)
        )
    except WidgetConfigNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Widget config not found")
    return config


@router.post("/{chatbot_id}/widget-config/avatar", response_model=WidgetConfigAdminResponse)
async def upload_widget_avatar(
    organization_id: int,
    chatbot_id: int,
    file: UploadFile = File(...),
    _membership: Membership = Depends(require_organization_role(MembershipRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Upload/replace the widget's avatar image (admin+). PNG/JPEG/WebP only,
    validated by file content, not extension or client Content-Type."""
    await _get_chatbot_or_404(db, organization_id, chatbot_id)
    content = await file.read()
    try:
        config = await WidgetConfigService(db).set_avatar(chatbot_id, content)
    except WidgetConfigNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Widget config not found")
    except ImageTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Image too large"
        )
    except InvalidImageError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported image type (PNG, JPEG, WebP only)",
        )
    return config


@router.delete("/{chatbot_id}/widget-config", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_widget_config(
    organization_id: int,
    chatbot_id: int,
    _membership: Membership = Depends(require_organization_role(MembershipRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    await _get_chatbot_or_404(db, organization_id, chatbot_id)
    await WidgetConfigService(db).revoke(chatbot_id)


@router.get("/{chatbot_id}/widget-config", response_model=WidgetConfigAdminResponse)
async def get_widget_config(
    organization_id: int,
    chatbot_id: int,
    _membership: Membership = Depends(require_organization_role(MembershipRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    await _get_chatbot_or_404(db, organization_id, chatbot_id)
    config = await WidgetConfigService(db).get(chatbot_id)
    return config


@router.delete("/{chatbot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chatbot(
    organization_id: int,
    chatbot_id: int,
    _membership: Membership = Depends(require_organization_role(MembershipRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    try:
        await ChatbotService(db).delete(organization_id, chatbot_id)
    except ChatbotNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found")
