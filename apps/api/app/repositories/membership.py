"""Membership repository — data access for memberships."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Membership, User
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

    async def get_by_id(self, organization_id: int, membership_id: int) -> Membership | None:
        result = await self.db.execute(
            select(Membership).where(
                Membership.id == membership_id,
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

    async def list_for_organization(
        self, organization_id: int
    ) -> list[tuple[Membership, str, str]]:
        """Membership rows joined with their user's email/full name.

        Selects plain columns (not the ORM relationship) so callers never touch
        lazy-loaded attributes under the async session — a single query gives
        the frontend everything it needs without a second round-trip per row.
        """
        result = await self.db.execute(
            select(Membership, User.email, User.full_name)
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == organization_id)
            .order_by(Membership.id)
        )
        return [(membership, email, full_name) for membership, email, full_name in result.all()]

    async def count_owners(self, organization_id: int) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.organization_id == organization_id,
                Membership.role == MembershipRole.OWNER,
            )
        )
        return result.scalar_one()

    async def delete(self, membership: Membership) -> None:
        await self.db.delete(membership)
