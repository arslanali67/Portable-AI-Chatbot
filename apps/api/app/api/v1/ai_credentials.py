"""BYOK AI provider credential endpoints — organization-scoped, ADMIN+ only.

Write-only: the raw key is never returned, only a masked last-4 indicator.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.registry import model_registry, provider_registry
from app.core.database import get_db
from app.core.dependencies import require_organization_role
from app.models import Membership
from app.models.enums import MembershipRole
from app.schemas.ai_provider_credential import CredentialSet, CredentialStatusResponse
from app.services.ai_provider_credential import (
    AIProviderCredentialService,
    CredentialNotFoundError,
    InvalidCredentialError,
    UnknownProviderError,
)

router = APIRouter(
    prefix="/organizations/{organization_id}/ai-credentials", tags=["ai-credentials"]
)


def _get_service(db: AsyncSession = Depends(get_db)) -> AIProviderCredentialService:
    return AIProviderCredentialService(db, provider_registry, model_registry)


@router.get("", response_model=list[CredentialStatusResponse])
async def list_credentials(
    organization_id: int,
    _membership: Membership = Depends(require_organization_role(MembershipRole.ADMIN)),
    service: AIProviderCredentialService = Depends(_get_service),
):
    return await service.list_status(organization_id)


@router.put("/{provider_id}", response_model=CredentialStatusResponse)
async def set_credential(
    organization_id: int,
    provider_id: str,
    payload: CredentialSet,
    membership: Membership = Depends(require_organization_role(MembershipRole.ADMIN)),
    service: AIProviderCredentialService = Depends(_get_service),
):
    actor_user_id = membership.user_id
    try:
        return await service.set_credential(
            organization_id, provider_id, payload.api_key, actor_user_id
        )
    except UnknownProviderError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown provider")
    except InvalidCredentialError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Credential validation failed: {exc.detail}",
        )


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_credential(
    organization_id: int,
    provider_id: str,
    _membership: Membership = Depends(require_organization_role(MembershipRole.ADMIN)),
    service: AIProviderCredentialService = Depends(_get_service),
):
    try:
        await service.remove_credential(organization_id, provider_id)
    except CredentialNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
