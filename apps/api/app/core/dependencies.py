"""Shared FastAPI dependencies: current user, organization membership."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import Membership, Organization, User
from app.models.enums import MembershipRole
from app.repositories.membership import MembershipRepository
from app.repositories.organization import OrganizationRepository
from app.repositories.user import UserRepository

bearer_scheme = HTTPBearer(auto_error=False)

_ROLE_RANK = {
    MembershipRole.MEMBER: 1,
    MembershipRole.ADMIN: 2,
    MembershipRole.OWNER: 3,
}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate Bearer JWT, load user from database, check active."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(credentials.credentials)
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await UserRepository(db).get(int(user_id))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_organization_membership(
    organization_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> tuple[Organization, Membership]:
    """Verify organization exists and current user belongs to it.

    Membership is always checked — knowing an organization_id grants nothing.
    """
    organization = await OrganizationRepository(db).get(organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    membership = await MembershipRepository(db).get(user.id, organization_id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )
    # Checked after membership, not before: a non-member must never learn
    # an organization's disabled status — the existing "organization_id
    # never grants access by itself" invariant extends to this signal too.
    if organization.disabled_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This organization has been disabled",
        )
    return organization, membership


async def require_platform_admin(user: User = Depends(get_current_user)) -> User:
    """Require the current user to be a platform admin.

    Independent of organization membership/roles — no MembershipRole,
    including OWNER, satisfies this. Platform-admin status grants no
    access to any organization's message/conversation content,
    system_prompt, or credential material — with one narrow, explicit
    exception: the platform dashboard's aggregate/metadata-only reads
    across organizations (app/api/v1/platform.py, architecture.md §8a),
    gated by this exact dependency. No other route, and no other data
    category, is affected.
    """
    if not user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin access required",
        )
    return user


def require_organization_role(required_role: MembershipRole):
    """Dependency factory: require membership with at least the given role.

    Usage: Depends(require_organization_role(MembershipRole.ADMIN))
    Returns the Membership so handlers can read the role.
    """

    async def dependency(
        organization_id: int,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> Membership:
        organization = await OrganizationRepository(db).get(organization_id)
        if organization is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found"
            )
        membership = await MembershipRepository(db).get(user.id, organization_id)
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of this organization",
            )
        # Checked after membership, not before: a non-member must never
        # learn an organization's disabled status.
        if organization.disabled_at is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This organization has been disabled",
            )
        if _ROLE_RANK.get(membership.role, 0) < _ROLE_RANK[required_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role for this organization",
            )
        return membership

    return dependency
