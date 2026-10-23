import logging
from datetime import UTC, datetime
from secrets import compare_digest

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.observability import MIGRATION_AT_HEAD, REFRESH_SESSIONS
from app.db.session import get_db
from app.models.auth import AuthIdentity, RefreshSession
from app.models.domain import MembershipRole, Tenant, TenantMembership, User
from app.schemas.domain import HealthResponse
from app.services.readiness import database_is_at_migration_head
from app.services.storage import (
    ObjectStorageUnavailableError,
    UploadObjectStorage,
    get_upload_storage,
)

router = APIRouter(prefix="/health", tags=["system"])
logger = logging.getLogger(__name__)


async def has_active_local_administrator(db: AsyncSession) -> bool:
    administrator_id = await db.scalar(
        select(TenantMembership.user_id)
        .join(User, User.id == TenantMembership.user_id)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .join(
            AuthIdentity,
            (AuthIdentity.user_id == User.id) & (AuthIdentity.provider == "local"),
        )
        .where(
            TenantMembership.role == MembershipRole.ADMIN,
            User.is_active.is_(True),
            Tenant.is_active.is_(True),
            AuthIdentity.password_hash.is_not(None),
        )
        .limit(1)
    )
    return administrator_id is not None


async def has_active_sso_administrator(db: AsyncSession, provider: str) -> bool:
    administrator_id = await db.scalar(
        select(TenantMembership.user_id)
        .join(User, User.id == TenantMembership.user_id)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .join(
            AuthIdentity,
            (AuthIdentity.user_id == User.id) & (AuthIdentity.provider == provider),
        )
        .where(
            TenantMembership.role == MembershipRole.ADMIN,
            User.is_active.is_(True),
            Tenant.is_active.is_(True),
        )
        .limit(1)
    )
    return administrator_id is not None


@router.get("/live", response_model=HealthResponse)
async def liveness(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(status="ok", service=settings.app_name, environment=settings.app_env)


@router.get("/ready", response_model=HealthResponse)
async def readiness(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    storage: UploadObjectStorage = Depends(get_upload_storage),
) -> HealthResponse:
    try:
        await db.execute(text("SELECT 1"))
        if settings.readiness_require_migration_head and not await database_is_at_migration_head(
            db
        ):
            logger.error("Readiness check failed: database migration is not at application head")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service is not ready.",
            )
        if settings.auth_mode in {"local", "hybrid"} and not await has_active_local_administrator(
            db
        ):
            logger.error("Readiness check failed: active local administrator is not provisioned")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service is not ready.",
            )
        if settings.auth_mode == "oidc" and not await has_active_sso_administrator(
            db, settings.oidc_provider_id
        ):
            logger.error("Readiness check failed: active SSO administrator is not provisioned")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service is not ready.",
            )
        await storage.check()
    except SQLAlchemyError:
        logger.error("Readiness check failed: database unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service is not ready.",
        ) from None
    except ObjectStorageUnavailableError:
        logger.error("Readiness check failed: object storage unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service is not ready.",
        ) from None

    return HealthResponse(status="ready", service=settings.app_name, environment=settings.app_env)


@router.get("/metrics", include_in_schema=False)
async def metrics(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    if not settings.metrics_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")

    scheme, _, supplied_token = request.headers.get("authorization", "").partition(" ")
    if (
        scheme.casefold() != "bearer"
        or not supplied_token
        or not compare_digest(supplied_token, settings.metrics_bearer_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Metrics authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    now = datetime.now(UTC)
    active_sessions = await db.scalar(
        select(func.count())
        .select_from(RefreshSession)
        .where(RefreshSession.revoked_at.is_(None), RefreshSession.expires_at > now)
    )
    revoked_sessions = await db.scalar(
        select(func.count())
        .select_from(RefreshSession)
        .where(RefreshSession.revoked_at.is_not(None))
    )
    REFRESH_SESSIONS.labels(state="active").set(active_sessions or 0)
    REFRESH_SESSIONS.labels(state="revoked").set(revoked_sessions or 0)
    try:
        migration_at_head = await database_is_at_migration_head(db)
    except SQLAlchemyError:
        migration_at_head = False
    MIGRATION_AT_HEAD.set(1 if migration_at_head else 0)

    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
        headers={"Cache-Control": "no-store"},
    )
