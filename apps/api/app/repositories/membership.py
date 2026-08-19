"""Membership repository — data access for memberships."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Membership
from app.models.enums import MembershipRole


class MembershipRepository:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def get(self, user_id: int, organization_id: int) -> Membership | None:
        result = await self.db.execute(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self, *, user_id: int, organization_id: int, role: MembershipRole
    ) -> Membership:
        membership = Membership(user_id=user_id, organization_id=organization_id, role=role)
        self.db.add(membership)
        return membership
