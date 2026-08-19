"""Organization service — creation with owner membership, listing."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Organization, User
from app.models.enums import MembershipRole
from app.repositories.membership import MembershipRepository
from app.repositories.organization import OrganizationRepository
from app.schemas.organization import OrganizationCreate


class DuplicateSlugError(Exception):
    pass


class OrganizationService:
    def __init__(self, db_session: AsyncSession):
        self.organizations = OrganizationRepository(db_session)
        self.memberships = MembershipRepository(db_session)

    async def create(self, user: User, payload: OrganizationCreate) -> Organization:
        slug = payload.slug.lower()
        existing = await self.organizations.get_by_slug(slug)
        if existing is not None:
            raise DuplicateSlugError()

        organization = await self.organizations.create(name=payload.name, slug=slug)
        # Flush so organization.id is assigned before creating the membership.
        await self.organizations.db.flush()
        await self.memberships.create(
            user_id=user.id, organization_id=organization.id, role=MembershipRole.OWNER
        )
        try:
            await self.organizations.db.commit()
        except IntegrityError as exc:
            await self.organizations.db.rollback()
            if "uq_organizations_slug" in str(exc.orig):
                raise DuplicateSlugError()
            raise
        await self.organizations.db.refresh(organization)
        return organization

    async def list_for_user(self, user: User) -> list[Organization]:
        return await self.organizations.list_for_user(user.id)
