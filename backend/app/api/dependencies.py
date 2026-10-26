from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Path, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.permissions import Permission, permissions_for_role, resolve_membership_role
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.domain import MembershipRole, Tenant, TenantMembership, User
from app.services.auth import add_auth_event, request_fingerprints
from app.services.readiness import IngestionReadinessError, api_ingestion_is_ready

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class TenantContext:
    tenant: Tenant
    user: User
    role: MembershipRole
    permissions: frozenset[Permission]


def require_document_ingestion_enabled(
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.document_ingestion_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "DOCUMENT_INGESTION_DISABLED",
                "message": "Document ingestion is unavailable.",
            },
        )


async def ensure_document_ingestion_ready(
    settings: Settings = Depends(get_settings),
) -> None:
    require_document_ingestion_enabled(settings)
    try:
        await api_ingestion_is_ready(settings)
    except IngestionReadinessError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "DOCUMENT_INGESTION_UNREADY",
                "message": "Document ingestion is temporarily unavailable.",
            },
        ) from None


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
        identity = decode_access_token(credentials.credentials, settings)
        user = await db.get(User, identity.user_id)
        if user is not None and user.auth_version != identity.auth_version:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired access token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    if user is None or not user.is_active:
        raise HTTPException(status_code=403, detail="User is not provisioned or is inactive.")
    return user


async def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User | None:
    if credentials is None:
        return None
    return await get_current_user(credentials=credentials, db=db, settings=settings)


async def require_tenant_member(
    request: Request,
    tenant_id: UUID = Path(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TenantContext:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None or not tenant.is_active:
        ip_hash, user_agent_hash = request_fingerprints(request, settings)
        add_auth_event(
            db,
            event_type="tenant_access_denied",
            success=False,
            user_id=user.id,
            subject_hash=None,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
            details={"tenant_id": str(tenant_id), "reason": "tenant_unavailable"},
        )
        await db.commit()
        raise HTTPException(status_code=404, detail="Tenant not found.")

    membership = await db.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user.id,
        )
    )
    if membership is None:
        ip_hash, user_agent_hash = request_fingerprints(request, settings)
        add_auth_event(
            db,
            event_type="tenant_access_denied",
            success=False,
            user_id=user.id,
            subject_hash=None,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
            details={"tenant_id": str(tenant_id), "reason": "membership_missing"},
        )
        await db.commit()
        raise HTTPException(status_code=403, detail="User is not a member of this tenant.")

    role = resolve_membership_role(membership.role)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this tenant.",
        )

    return TenantContext(
        tenant=tenant,
        user=user,
        role=role,
        permissions=permissions_for_role(role),
    )
