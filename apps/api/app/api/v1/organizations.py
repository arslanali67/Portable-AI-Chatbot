"""Organization endpoints: create, list."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models import User
from app.schemas.organization import OrganizationCreate, OrganizationResponse
from app.services.organization import DuplicateSlugError, OrganizationService

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
