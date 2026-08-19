"""AI management endpoints — read-only provider/model discovery.

Authenticated users see safe metadata only; credentials never returned.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.ai.registry import model_registry, provider_registry
from app.core.dependencies import get_current_user
from app.models import User
from app.schemas.ai_management import ModelResponse, ProviderResponse
from app.services.ai_management import (
    AIManagementService,
    ModelNotFoundError,
    ProviderNotFoundError,
)

router = APIRouter(prefix="/ai", tags=["ai-management"])

_management = AIManagementService(provider_registry, model_registry)


@router.get("/providers", response_model=list[ProviderResponse])
async def list_providers(_user: User = Depends(get_current_user)):
    return _management.list_providers()


@router.get("/providers/{provider_id}", response_model=ProviderResponse)
async def get_provider(provider_id: str, _user: User = Depends(get_current_user)):
    try:
        return _management.get_provider(provider_id)
    except ProviderNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")


@router.get("/providers/{provider_id}/models", response_model=list[ModelResponse])
async def list_models(provider_id: str, _user: User = Depends(get_current_user)):
    try:
        return _management.list_models(provider_id)
    except ProviderNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")


@router.get(
    "/providers/{provider_id}/models/{model_id}", response_model=ModelResponse
)
async def get_model(provider_id: str, model_id: str, _user: User = Depends(get_current_user)):
    try:
        return _management.get_model(provider_id, model_id)
    except ProviderNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    except ModelNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
