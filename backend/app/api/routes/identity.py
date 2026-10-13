from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.domain import Tenant, TenantMembership, User
from app.schemas.domain import CurrentUserResponse, TenantResponse

router = APIRouter(tags=["identity"])


async def _get_user_tenants(db: AsyncSession, user_id) -> list[Tenant]:
    result = await db.scalars(
        select(Tenant)
        .join(TenantMembership, TenantMembership.tenant_id == Tenant.id)
        .where(TenantMembership.user_id == user_id, Tenant.is_active.is_(True))
        .order_by(Tenant.name)
    )
    return list(result)


@router.get("/me", response_model=CurrentUserResponse)
async def current_user(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> CurrentUserResponse:
    tenants = await _get_user_tenants(db, user.id)
    return CurrentUserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        tenants=[TenantResponse.model_validate(tenant) for tenant in tenants],
    )


@router.get("/me/tenants", response_model=list[TenantResponse])
async def current_user_tenants(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[Tenant]:
    return await _get_user_tenants(db, user.id)
