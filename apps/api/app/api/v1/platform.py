"""Platform-owner dashboard endpoints — read-only cross-organization
visibility plus reversible disable/enable, all gated by
require_platform_admin. See architecture.md §8a.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_platform_admin
from app.models import User
from app.schemas.billing import (
    StripeCredentialSet,
    StripeCredentialStatusResponse,
    SubscriptionOverrideRequest,
    SubscriptionResponse,
)
from app.schemas.platform import (
    OrganizationDisableRequest,
    PlatformOrganizationDetail,
    PlatformOrganizationListResponse,
    PlatformOrganizationSummary,
)
from app.services.billing import BillingService
from app.services.billing import OrganizationNotFoundError as BillingOrganizationNotFoundError
from app.services.platform import OrganizationNotFoundError, PlatformService
from app.services.stripe_credential import StripeCredentialService

router = APIRouter(prefix="/platform", tags=["platform-admin"])


def _get_service(db: AsyncSession = Depends(get_db)) -> PlatformService:
    return PlatformService(db)


def _get_billing_service(db: AsyncSession = Depends(get_db)) -> BillingService:
    return BillingService(db)


def _get_stripe_credential_service(db: AsyncSession = Depends(get_db)) -> StripeCredentialService:
    return StripeCredentialService(db)


@router.get("/organizations", response_model=PlatformOrganizationListResponse)
async def list_organizations(
    _admin: User = Depends(require_platform_admin),
    service: PlatformService = Depends(_get_service),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    items, total = await service.list_organizations(limit=limit, offset=offset)
    return PlatformOrganizationListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/organizations/{organization_id}", response_model=PlatformOrganizationDetail)
async def get_organization(
    organization_id: int,
    _admin: User = Depends(require_platform_admin),
    service: PlatformService = Depends(_get_service),
):
    try:
        return await service.get_organization_detail(organization_id)
    except OrganizationNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")


@router.post("/organizations/{organization_id}/disable", response_model=PlatformOrganizationSummary)
async def disable_organization(
    organization_id: int,
    payload: OrganizationDisableRequest,
    _admin: User = Depends(require_platform_admin),
    service: PlatformService = Depends(_get_service),
):
    try:
        return await service.disable_organization(organization_id, message=payload.message)
    except OrganizationNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")


@router.post("/organizations/{organization_id}/enable", response_model=PlatformOrganizationSummary)
async def enable_organization(
    organization_id: int,
    _admin: User = Depends(require_platform_admin),
    service: PlatformService = Depends(_get_service),
):
    try:
        return await service.enable_organization(organization_id)
    except OrganizationNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")


@router.patch(
    "/organizations/{organization_id}/subscription", response_model=SubscriptionResponse
)
async def override_subscription(
    organization_id: int,
    payload: SubscriptionOverrideRequest,
    _admin: User = Depends(require_platform_admin),
    service: BillingService = Depends(_get_billing_service),
):
    """Directly sets an organization's tier/status, bypassing Stripe
    entirely (e.g. to comp an account) — upserts the subscriptions row,
    creating one if absent. A later real webhook event overwrites this
    normally via the same upsert path; no special-casing."""
    try:
        subscription = await service.set_manual_subscription(
            organization_id, tier=payload.tier, status=payload.status
        )
    except BillingOrganizationNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return SubscriptionResponse(
        tier=subscription.tier,
        status=subscription.status,
        current_period_end=subscription.current_period_end,
    )


@router.get("/settings/stripe", response_model=StripeCredentialStatusResponse | None)
async def get_stripe_settings(
    _admin: User = Depends(require_platform_admin),
    service: StripeCredentialService = Depends(_get_stripe_credential_service),
):
    return await service.get_status()


@router.put("/settings/stripe", response_model=StripeCredentialStatusResponse)
async def set_stripe_settings(
    payload: StripeCredentialSet,
    admin: User = Depends(require_platform_admin),
    service: StripeCredentialService = Depends(_get_stripe_credential_service),
):
    return await service.set_credential(payload.secret_key, admin.id)
