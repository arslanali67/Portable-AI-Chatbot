"""AI management endpoints — read-only provider/model discovery, plus
platform-admin enable/disable mutation.

Authenticated users see safe metadata only; credentials never returned.
Mutation is gated by require_platform_admin, independent of any
organization role.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.registry import model_registry, provider_registry
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_platform_admin
from app.models import User
from app.schemas.ai_management import ModelResponse, ModelUpdate, ProviderResponse, ProviderUpdate
from app.services.ai_management import (
    AIManagementService,
    ModelNotFoundError,
    ProviderNotFoundError,
)
from app.services.ai_provider_override import AIProviderOverrideService

router = APIRouter(prefix="/ai", tags=["ai-management"])


def _get_management(db: AsyncSession = Depends(get_db)) -> AIManagementService:
    return AIManagementService(provider_registry, model_registry, AIProviderOverrideService(db))


@router.get("/providers", response_model=list[ProviderResponse])
async def list_providers(
    _user: User = Depends(get_current_user),
    management: AIManagementService = Depends(_get_management),
):
    return await management.list_providers()


@router.get("/providers/{provider_id}", response_model=ProviderResponse)
async def get_provider(
    provider_id: str,
    _user: User = Depends(get_current_user),
    management: AIManagementService = Depends(_get_management),
):
    try:
        return await management.get_provider(provider_id)
    except ProviderNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")


@router.get("/providers/{provider_id}/models", response_model=list[ModelResponse])
async def list_models(
    provider_id: str,
    _user: User = Depends(get_current_user),
    management: AIManagementService = Depends(_get_management),
):
    try:
        return await management.list_models(provider_id)
    except ProviderNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")


@router.get(
    "/providers/{provider_id}/models/{model_id}", response_model=ModelResponse
)
async def get_model(
    provider_id: str,
    model_id: str,
    _user: User = Depends(get_current_user),
    management: AIManagementService = Depends(_get_management),
):
    try:
        return await management.get_model(provider_id, model_id)
    except ProviderNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    except ModelNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")


@router.patch("/providers/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: str,
    payload: ProviderUpdate,
    admin: User = Depends(require_platform_admin),
    management: AIManagementService = Depends(_get_management),
):
    try:
        return await management.set_provider_disabled(provider_id, payload.disabled, admin.id)
    except ProviderNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")


@router.patch(
    "/providers/{provider_id}/models/{model_id}", response_model=ModelResponse
)
async def update_model(
    provider_id: str,
    model_id: str,
    payload: ModelUpdate,
    admin: User = Depends(require_platform_admin),
    management: AIManagementService = Depends(_get_management),
):
    try:
        return await management.set_model_disabled(
            provider_id, model_id, payload.disabled, admin.id
        )
    except ProviderNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    except ModelNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
