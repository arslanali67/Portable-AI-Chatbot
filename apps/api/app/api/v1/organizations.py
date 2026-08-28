"""Organization endpoints: create, list, detail, rename, delete, members.

Authorization: read (org detail, member list) requires MEMBER+; rename
requires ADMIN+; delete requires OWNER only; adding/removing/changing members
requires ADMIN+, except a member may always remove themselves. Owner-specific
restrictions (an admin can never create, promote to, or modify an OWNER
membership) and the last-owner guard are enforced in MembershipService, not
here — routers stay thin per the existing layering.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    get_current_user,
    require_organization_membership,
    require_organization_role,
)
from app.models import Membership, Organization, User
from app.models.enums import MembershipRole
from app.schemas.organization import (
    MembershipCreate,
    MembershipResponse,
    MembershipUpdate,
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
)
from app.services.membership import (
    AlreadyMemberError,
    InsufficientRoleError,
    LastOwnerError,
    MembershipNotFoundError,
    MembershipService,
    UserNotFoundError,
)
from app.services.organization import (
    DuplicateSlugError,
    OrganizationNotFoundError,
    OrganizationService,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        organization = await OrganizationService(db).create(current_user, payload)
    except DuplicateSlugError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already taken")
    return organization


@router.get("", response_model=list[OrganizationResponse])
async def list_organizations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await OrganizationService(db).list_for_user(current_user)


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: int,
    _membership: Membership = Depends(require_organization_role(MembershipRole.MEMBER)),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await OrganizationService(db).get(organization_id)
    except OrganizationNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")


@router.patch("/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    organization_id: int,
    payload: OrganizationUpdate,
    _membership: Membership = Depends(require_organization_role(MembershipRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await OrganizationService(db).update(organization_id, payload)
    except OrganizationNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")


@router.delete("/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    organization_id: int,
    _membership: Membership = Depends(require_organization_role(MembershipRole.OWNER)),
    db: AsyncSession = Depends(get_db),
):
    try:
        await OrganizationService(db).delete(organization_id)
    except OrganizationNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")


@router.get("/{organization_id}/members", response_model=list[MembershipResponse])
async def list_members(
    organization_id: int,
    _membership: Membership = Depends(require_organization_role(MembershipRole.MEMBER)),
    db: AsyncSession = Depends(get_db),
):
    return await MembershipService(db).list(organization_id)


@router.post(
    "/{organization_id}/members",
    response_model=MembershipResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    organization_id: int,
    payload: MembershipCreate,
    membership: Membership = Depends(require_organization_role(MembershipRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await MembershipService(db).add(
            organization_id, payload, actor_role=membership.role
        )
    except InsufficientRoleError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner can create an owner membership",
        )
    except UserNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    except AlreadyMemberError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="User is already a member"
        )


@router.patch("/{organization_id}/members/{membership_id}", response_model=MembershipResponse)
async def update_member_role(
    organization_id: int,
    membership_id: int,
    payload: MembershipUpdate,
    membership: Membership = Depends(require_organization_role(MembershipRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await MembershipService(db).update_role(
            organization_id, membership_id, payload, actor_role=membership.role
        )
    except MembershipNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found")
    except InsufficientRoleError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner can create, promote to, or modify an owner membership",
        )
    except LastOwnerError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization must keep at least one owner",
        )


@router.delete("/{organization_id}/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    organization_id: int,
    membership_id: int,
    current_user: User = Depends(get_current_user),
    actor: tuple[Organization, Membership] = Depends(require_organization_membership),
    db: AsyncSession = Depends(get_db),
):
    _organization, actor_membership = actor
    try:
        await MembershipService(db).remove(
            organization_id,
            membership_id,
            actor_user_id=current_user.id,
            actor_role=actor_membership.role,
        )
    except MembershipNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found")
    except InsufficientRoleError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient role to remove this member",
        )
    except LastOwnerError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization must keep at least one owner",
        )
