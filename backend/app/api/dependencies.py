from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import decode_oidc_token
from app.db.session import get_db
from app.models.domain import Tenant, TenantMembership, User

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class TenantContext:
    tenant: Tenant
    user: User
    role: str


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if settings.auth_mode == "development":
        user = await db.get(User, settings.dev_user_id)
    else:
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer access token is required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        identity = decode_oidc_token(credentials.credentials, settings)
        user = await db.scalar(select(User).where(User.external_subject == identity.subject))

    if user is None or not user.is_active:
        raise HTTPException(status_code=403, detail="User is not provisioned or is inactive.")
    return user


async def require_tenant_member(
    tenant_id: UUID = Path(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None or not tenant.is_active:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    membership = await db.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="User is not a member of this tenant.")

    return TenantContext(tenant=tenant, user=user, role=membership.role)
