"""Organization repository — data access for organizations."""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Membership, Organization


class OrganizationRepository:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def get(self, organization_id: int) -> Organization | None:
        return await self.db.get(Organization, organization_id)

    async def list_all(self, *, limit: int, offset: int) -> tuple[list[Organization], int]:
        """Every organization on the platform, unscoped by membership.

        Platform-dashboard-only (app/services/platform.py) — the one
        deliberate cross-tenant listing in this codebase. See
        architecture.md §8a.
        """
        total = await self.db.scalar(select(func.count()).select_from(Organization))
        result = await self.db.execute(
            select(Organization).order_by(Organization.id).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), total or 0

    async def disable(self, organization: Organization, *, message: str | None) -> Organization:
        organization.disabled_at = datetime.now(timezone.utc)
        organization.disabled_message = message
        return organization

    async def enable(self, organization: Organization) -> Organization:
        organization.disabled_at = None
        organization.disabled_message = None
        return organization

    async def get_by_slug(self, slug: str) -> Organization | None:
        result = await self.db.execute(select(Organization).where(Organization.slug == slug))
        return result.scalar_one_or_none()

    async def create(self, *, name: str, slug: str) -> Organization:
        organization = Organization(name=name, slug=slug)
        self.db.add(organization)
        return organization

    async def list_for_user(self, user_id: int) -> list[Organization]:
        result = await self.db.execute(
            select(Organization)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user_id)
            .order_by(Organization.id)
        )
        return list(result.scalars().all())

    async def update(self, organization: Organization, *, name: str) -> Organization:
        organization.name = name
        return organization

    async def delete(self, organization: Organization) -> None:
        await self.db.delete(organization)
