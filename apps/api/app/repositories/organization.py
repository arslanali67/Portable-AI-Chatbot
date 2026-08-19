"""Organization repository — data access for organizations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Membership, Organization


class OrganizationRepository:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def get(self, organization_id: int) -> Organization | None:
        return await self.db.get(Organization, organization_id)

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
