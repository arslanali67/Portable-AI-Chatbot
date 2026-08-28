"""Membership service — organization member management business rules.

Owner/admin/member semantics enforced here (not just in routers):
- ADMIN can add/remove/change the role of MEMBER and ADMIN memberships.
- Only OWNER can create an OWNER membership, promote to OWNER, or modify an
  existing OWNER's role.
- ADMIN can never remove an OWNER; any member may remove themselves
  regardless of role.
- No operation may ever leave an organization with zero OWNER memberships
  (the "last owner" guard) — this includes an owner demoting or removing
  themselves.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import MembershipRole
from app.repositories.membership import MembershipRepository
from app.repositories.user import UserRepository
from app.schemas.organization import MembershipCreate, MembershipResponse, MembershipUpdate


class MembershipNotFoundError(Exception):
    pass


class AlreadyMemberError(Exception):
    pass


class UserNotFoundError(Exception):
    pass


class LastOwnerError(Exception):
    pass


class InsufficientRoleError(Exception):
    """Actor lacks the role required for this action on this membership."""

    pass


def _to_response(membership, email: str, full_name: str) -> MembershipResponse:
    return MembershipResponse(
        id=membership.id,
        organization_id=membership.organization_id,
        user_id=membership.user_id,
        role=membership.role,
        created_at=membership.created_at,
        user_email=email,
        user_full_name=full_name,
    )


class MembershipService:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.memberships = MembershipRepository(db_session)
        self.users = UserRepository(db_session)

    async def list(self, organization_id: int) -> list[MembershipResponse]:
        rows = await self.memberships.list_for_organization(organization_id)
        return [_to_response(m, email, full_name) for m, email, full_name in rows]

    async def add(
        self,
        organization_id: int,
        payload: MembershipCreate,
        *,
        actor_role: MembershipRole,
    ) -> MembershipResponse:
        if payload.role == MembershipRole.OWNER and actor_role != MembershipRole.OWNER:
            raise InsufficientRoleError()

        user = await self.users.get_by_email(payload.email.lower())
        if user is None:
            raise UserNotFoundError()

        existing = await self.memberships.get(user.id, organization_id)
        if existing is not None:
            raise AlreadyMemberError()

        membership = await self.memberships.create(
            user_id=user.id, organization_id=organization_id, role=payload.role
        )
        await self.db.commit()
        await self.db.refresh(membership)
        return _to_response(membership, user.email, user.full_name)

    async def update_role(
        self,
        organization_id: int,
        membership_id: int,
        payload: MembershipUpdate,
        *,
        actor_role: MembershipRole,
    ) -> MembershipResponse:
        membership = await self.memberships.get_by_id(organization_id, membership_id)
        if membership is None:
            raise MembershipNotFoundError()

        # Only an owner may touch an existing owner's role or promote anyone
        # to owner — an admin can never create, escalate to, or demote owner.
        if membership.role == MembershipRole.OWNER and actor_role != MembershipRole.OWNER:
            raise InsufficientRoleError()
        if payload.role == MembershipRole.OWNER and actor_role != MembershipRole.OWNER:
            raise InsufficientRoleError()

        if membership.role == MembershipRole.OWNER and payload.role != MembershipRole.OWNER:
            owners = await self.memberships.count_owners(organization_id)
            if owners <= 1:
                raise LastOwnerError()

        membership.role = payload.role
        await self.db.commit()
        await self.db.refresh(membership)
        user = await self.users.get(membership.user_id)
        return _to_response(membership, user.email, user.full_name)

    async def remove(
        self,
        organization_id: int,
        membership_id: int,
        *,
        actor_user_id: int,
        actor_role: MembershipRole,
    ) -> None:
        membership = await self.memberships.get_by_id(organization_id, membership_id)
        if membership is None:
            raise MembershipNotFoundError()

        is_self = membership.user_id == actor_user_id
        if not is_self:
            if actor_role not in (MembershipRole.ADMIN, MembershipRole.OWNER):
                raise InsufficientRoleError()
            if membership.role == MembershipRole.OWNER and actor_role != MembershipRole.OWNER:
                raise InsufficientRoleError()

        if membership.role == MembershipRole.OWNER:
            owners = await self.memberships.count_owners(organization_id)
            if owners <= 1:
                raise LastOwnerError()

        await self.memberships.delete(membership)
        await self.db.commit()
