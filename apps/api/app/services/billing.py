"""Billing service — Stripe Checkout initiation, webhook event handling,
invoice listing, and the platform-admin manual subscription override.

Never mutates the subscriptions table from the checkout path — a Checkout
session can be abandoned; only a confirmed webhook event changes state.
See architecture.md §8b.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.stripe_client import StripeClient
from app.billing.tiers import get_tier
from app.core.logging import get_logger
from app.models import Organization, Subscription
from app.repositories.organization import OrganizationRepository
from app.repositories.subscription import SubscriptionRepository
from app.services.stripe_credential import StripeCredentialService

logger = get_logger("portableai.billing")

_LAPSED_MESSAGE = "This organization's subscription has lapsed."


class OrganizationNotFoundError(Exception):
    pass


class StripeNotConfiguredError(Exception):
    """No platform Stripe secret key has been set yet (platform dashboard)."""


class BillingService:
    def __init__(self, db_session: AsyncSession, stripe_client: StripeClient | None = None) -> None:
        self.db = db_session
        self.subscriptions = SubscriptionRepository(db_session)
        self.organizations = OrganizationRepository(db_session)
        self._stripe_client = stripe_client

    async def _get_stripe_client(self) -> StripeClient:
        if self._stripe_client is not None:
            return self._stripe_client
        api_key = await StripeCredentialService(self.db).resolve_decrypted()
        if api_key is None:
            raise StripeNotConfiguredError()
        self._stripe_client = StripeClient(api_key)
        return self._stripe_client

    async def create_checkout_session(
        self,
        organization_id: int,
        tier_id: str,
        *,
        actor_email: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
        tier = get_tier(tier_id)  # raises UnknownTierError
        client = await self._get_stripe_client()
        existing = await self.subscriptions.get_for_organization(organization_id)
        customer_id = existing.stripe_customer_id if existing else None
        return client.create_checkout_session(
            customer_id=customer_id,
            customer_email=actor_email,
            price_id=tier.stripe_price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"organization_id": str(organization_id), "tier": tier_id},
        )

    async def list_invoices(self, organization_id: int) -> list[dict[str, Any]]:
        sub = await self.subscriptions.get_for_organization(organization_id)
        if sub is None or sub.stripe_customer_id is None:
            return []
        client = await self._get_stripe_client()
        return client.list_invoices(customer_id=sub.stripe_customer_id)

    async def set_manual_subscription(
        self, organization_id: int, *, tier: str | None, status: str | None
    ) -> Subscription:
        organization = await self.organizations.get(organization_id)
        if organization is None:
            raise OrganizationNotFoundError(organization_id)
        subscription = await self.subscriptions.upsert(organization_id, tier=tier, status=status)
        await self.db.commit()
        await self.db.refresh(subscription)
        return subscription

    # --- webhook event handling ---

    async def handle_webhook_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        data = event.get("data", {}).get("object", {})
        if event_type == "checkout.session.completed":
            await self._handle_checkout_completed(data)
        elif event_type == "customer.subscription.updated":
            await self._handle_subscription_updated(data)
        elif event_type == "customer.subscription.deleted":
            await self._handle_subscription_deleted(data)
        elif event_type == "invoice.payment_failed":
            self._handle_payment_failed(data)
        # Any other event type is ignored — Stripe sends many events this
        # platform doesn't act on; ignoring unknown types is intentional,
        # not an oversight.

    async def _handle_checkout_completed(self, session: dict[str, Any]) -> None:
        metadata = session.get("metadata") or {}
        organization_id = metadata.get("organization_id")
        tier_id = metadata.get("tier")
        if organization_id is None or tier_id is None:
            logger.warning("checkout.session.completed missing organization_id/tier metadata")
            return
        await self.subscriptions.upsert(
            int(organization_id),
            tier=tier_id,
            status="active",
            stripe_customer_id=session.get("customer"),
            stripe_subscription_id=session.get("subscription"),
        )
        await self.db.commit()

    async def _handle_subscription_updated(self, subscription: dict[str, Any]) -> None:
        stripe_subscription_id = subscription.get("id")
        sub_row = await self.subscriptions.get_by_stripe_subscription_id(stripe_subscription_id)
        if sub_row is None:
            logger.warning(
                "customer.subscription.updated for unknown stripe_subscription_id=%s",
                stripe_subscription_id,
            )
            return

        new_status = subscription.get("status")
        previous_status = sub_row.status
        period_end_ts = subscription.get("current_period_end")
        current_period_end = (
            datetime.fromtimestamp(period_end_ts, tz=timezone.utc) if period_end_ts else None
        )
        organization_id = sub_row.organization_id
        await self.subscriptions.upsert(
            organization_id, status=new_status, current_period_end=current_period_end
        )
        await self.db.commit()

        organization = await self.organizations.get(organization_id)
        if organization is None:
            return
        if new_status == "canceled" and previous_status != "canceled":
            await self._disable_for_lapse(organization)
        elif new_status == "active" and previous_status != "active":
            await self._re_enable_after_recovery(organization)

    async def _handle_subscription_deleted(self, subscription: dict[str, Any]) -> None:
        stripe_subscription_id = subscription.get("id")
        sub_row = await self.subscriptions.get_by_stripe_subscription_id(stripe_subscription_id)
        if sub_row is None:
            return
        organization_id = sub_row.organization_id
        await self.subscriptions.upsert(organization_id, status="canceled")
        await self.db.commit()
        organization = await self.organizations.get(organization_id)
        if organization is not None:
            await self._disable_for_lapse(organization)

    def _handle_payment_failed(self, invoice: dict[str, Any]) -> None:
        # Grace period (approved decision): Stripe's own retry/dunning
        # window is the actual mechanism here — sync/log only, never an
        # immediate disable. Only the eventual `canceled` status (handled
        # in _handle_subscription_updated/_deleted) acts.
        logger.info(
            "Stripe invoice payment failed (customer=%s, invoice=%s) — grace period, no action taken",
            invoice.get("customer"),
            invoice.get("id"),
        )

    async def _disable_for_lapse(self, organization: Organization) -> None:
        # Never overwrite an existing disable (billing- or admin-set) —
        # avoids clobbering whatever reason is already recorded on repeat/
        # overlapping webhook deliveries.
        if organization.disabled_at is not None:
            return
        await self.organizations.disable(organization, message=_LAPSED_MESSAGE)
        await self.db.commit()

    async def _re_enable_after_recovery(self, organization: Organization) -> None:
        # Only undo a disable billing itself set — never silently clear an
        # unrelated platform-admin disable just because Stripe recovered.
        if organization.disabled_at is None or organization.disabled_message != _LAPSED_MESSAGE:
            return
        await self.organizations.enable(organization)
        await self.db.commit()
