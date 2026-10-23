from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.permissions import permissions_for_role
from app.db.session import get_db
from app.models.auth import AuthIdentity
from app.models.domain import Tenant, TenantMembership, User
from app.schemas.domain import CurrentUserResponse, TenantResponse

router = APIRouter(tags=["identity"])


async def _get_user_tenants(db: AsyncSession, user_id) -> list[TenantResponse]:
    result = await db.execute(
        select(Tenant, TenantMembership.role)
        .join(TenantMembership, TenantMembership.tenant_id == Tenant.id)
        .where(TenantMembership.user_id == user_id, Tenant.is_active.is_(True))
        .order_by(Tenant.name)
    )
    return [
        TenantResponse(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            role=role,
            permissions=sorted(permission.value for permission in permissions_for_role(role)),
        )
        for tenant, role in result.all()
    ]


@router.get("/me", response_model=CurrentUserResponse)
async def current_user(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> CurrentUserResponse:
    tenants = await _get_user_tenants(db, user.id)
    identities = list(await db.scalars(select(AuthIdentity).where(AuthIdentity.user_id == user.id)))
    identity_providers = sorted({identity.provider for identity in identities})
    has_local_password = any(
        identity.provider == "local" and bool(identity.password_hash) for identity in identities
    )
    return CurrentUserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        identity_providers=identity_providers,
        can_change_password=has_local_password,
        can_manage_sessions=True,
        tenants=tenants,
    )


@router.get("/me/tenants", response_model=list[TenantResponse])
async def current_user_tenants(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[TenantResponse]:
    return await _get_user_tenants(db, user.id)
