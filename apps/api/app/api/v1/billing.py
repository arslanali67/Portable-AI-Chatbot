"""Organization-scoped billing endpoints — Checkout initiation,
subscription status, and invoice history. OWNER-only: the same bar as
organization deletion, since this is a financial commitment.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_organization_role
from app.models import Membership, User
from app.models.enums import MembershipRole
from app.repositories.subscription import SubscriptionRepository
from app.schemas.billing import (
    CheckoutRequest,
    CheckoutResponse,
    InvoiceListResponse,
    InvoiceResponse,
    SubscriptionResponse,
)
from app.services.billing import BillingService, StripeNotConfiguredError
from app.billing.tiers import UnknownTierError

router = APIRouter(prefix="/organizations/{organization_id}/billing", tags=["billing"])


def _get_service(db: AsyncSession = Depends(get_db)) -> BillingService:
    return BillingService(db)


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout_session(
    organization_id: int,
    payload: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    _membership: Membership = Depends(require_organization_role(MembershipRole.OWNER)),
    service: BillingService = Depends(_get_service),
):
    success_url = f"{settings.frontend_base_url}/organizations/{organization_id}/billing?checkout=success"
    cancel_url = f"{settings.frontend_base_url}/organizations/{organization_id}/billing?checkout=cancel"
    try:
        checkout_url = await service.create_checkout_session(
            organization_id,
            payload.tier,
            actor_email=current_user.email,
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except UnknownTierError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown tier")
    except StripeNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Billing is not configured"
        )
    return CheckoutResponse(checkout_url=checkout_url)


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    organization_id: int,
    _membership: Membership = Depends(require_organization_role(MembershipRole.OWNER)),
    db: AsyncSession = Depends(get_db),
):
    subscription = await SubscriptionRepository(db).get_for_organization(organization_id)
    if subscription is None:
        return SubscriptionResponse(tier=None, status=None, current_period_end=None)
    return SubscriptionResponse(
        tier=subscription.tier,
        status=subscription.status,
        current_period_end=subscription.current_period_end,
    )


@router.get("/invoices", response_model=InvoiceListResponse)
async def list_invoices(
    organization_id: int,
    _membership: Membership = Depends(require_organization_role(MembershipRole.OWNER)),
    service: BillingService = Depends(_get_service),
):
    try:
        raw_invoices = await service.list_invoices(organization_id)
    except StripeNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Billing is not configured"
        )
    items = [
        InvoiceResponse(
            id=invoice["id"],
            created=invoice["created"],
            amount_paid=invoice["amount_paid"],
            currency=invoice["currency"],
            status=invoice["status"],
            hosted_invoice_url=invoice.get("hosted_invoice_url"),
        )
        for invoice in raw_invoices
    ]
    return InvoiceListResponse(items=items)
