"""Organization service — creation with owner membership, listing."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Organization, User
from app.models.enums import MembershipRole
from app.repositories.membership import MembershipRepository
from app.repositories.organization import OrganizationRepository
from app.schemas.organization import OrganizationCreate, OrganizationUpdate


class DuplicateSlugError(Exception):
    pass


class OrganizationNotFoundError(Exception):
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

    async def get(self, organization_id: int) -> Organization:
        organization = await self.organizations.get(organization_id)
        if organization is None:
            raise OrganizationNotFoundError()
        return organization

    async def update(self, organization_id: int, payload: OrganizationUpdate) -> Organization:
        organization = await self.get(organization_id)
        organization = await self.organizations.update(organization, name=payload.name)
        await self.organizations.db.commit()
        await self.organizations.db.refresh(organization)
        return organization

    async def delete(self, organization_id: int) -> None:
        organization = await self.get(organization_id)
        await self.organizations.delete(organization)
        await self.organizations.db.commit()
