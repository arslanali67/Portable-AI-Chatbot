"""Subscription repository — one row per organization that has ever
touched billing. No row = Free tier (see app/models/subscription.py)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription


class SubscriptionRepository:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def get_for_organization(self, organization_id: int) -> Subscription | None:
        result = await self.db.execute(
            select(Subscription).where(Subscription.organization_id == organization_id)
        )
        return result.scalar_one_or_none()

    async def get_by_stripe_subscription_id(self, stripe_subscription_id: str) -> Subscription | None:
        result = await self.db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == stripe_subscription_id
            )
        )
        return result.scalar_one_or_none()

    async def upsert(self, organization_id: int, **fields) -> Subscription:
        subscription = await self.get_for_organization(organization_id)
        if subscription is None:
            subscription = Subscription(organization_id=organization_id)
            self.db.add(subscription)
        for key, value in fields.items():
            setattr(subscription, key, value)
        return subscription
