import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException, Request, Response
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.observability import record_auth_event
from app.core.security import audit_fingerprint, new_refresh_token, token_digest
from app.models.auth import AuthEvent, PasswordResetToken, RefreshSession


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def request_fingerprints(request: Request, settings: Settings) -> tuple[str, str]:
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")[:512]
    return audit_fingerprint(client_ip, settings), audit_fingerprint(user_agent, settings)


def enforce_trusted_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in settings.cors_origin_list:
        raise HTTPException(status_code=403, detail="Request origin is not allowed.")


def set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.auth_refresh_cookie_name,
        value=token,
        max_age=settings.auth_refresh_token_days * 24 * 60 * 60,
        path=f"{settings.api_v1_prefix}/auth",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.auth_refresh_cookie_name,
        path=f"{settings.api_v1_prefix}/auth",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )
    response.headers["Cache-Control"] = "no-store"


async def login_is_rate_limited(
    db: AsyncSession, subject_hash: str, ip_hash: str, settings: Settings
) -> bool:
    cutoff = utc_now() - timedelta(minutes=settings.auth_login_window_minutes)
    base = [
        AuthEvent.event_type == "login",
        AuthEvent.success.is_(False),
        AuthEvent.created_at >= cutoff,
    ]
    subject_failures = await db.scalar(
        select(func.count())
        .select_from(AuthEvent)
        .where(*base, AuthEvent.subject_hash == subject_hash)
    )
    ip_failures = await db.scalar(
        select(func.count()).select_from(AuthEvent).where(*base, AuthEvent.ip_hash == ip_hash)
    )
    return (subject_failures or 0) >= settings.auth_login_subject_limit or (
        ip_failures or 0
    ) >= settings.auth_login_ip_limit


async def password_reset_is_rate_limited(
    db: AsyncSession, subject_hash: str, ip_hash: str, settings: Settings
) -> bool:
    cutoff = utc_now() - timedelta(minutes=settings.password_reset_window_minutes)
    base = [
        AuthEvent.event_type == "password_reset_requested",
        AuthEvent.created_at >= cutoff,
    ]
    subject_requests = await db.scalar(
        select(func.count())
        .select_from(AuthEvent)
        .where(*base, AuthEvent.subject_hash == subject_hash)
    )
    ip_requests = await db.scalar(
        select(func.count()).select_from(AuthEvent).where(*base, AuthEvent.ip_hash == ip_hash)
    )
    return (subject_requests or 0) >= settings.password_reset_subject_limit or (
        ip_requests or 0
    ) >= settings.password_reset_ip_limit


def new_password_reset_token() -> str:
    return secrets.token_urlsafe(32)


async def invalidate_unused_password_reset_tokens(
    db: AsyncSession, user_id: UUID, invalidated_at: datetime | None = None
) -> None:
    await db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None))
        .values(used_at=invalidated_at or utc_now())
    )


async def cleanup_password_reset_tokens(db: AsyncSession, retention_days: int) -> int:
    cutoff = utc_now() - timedelta(days=retention_days)
    result = await db.execute(
        delete(PasswordResetToken).where(
            or_(
                PasswordResetToken.expires_at < cutoff,
                PasswordResetToken.used_at < cutoff,
            )
        )
    )
    await db.commit()
    return result.rowcount or 0


def add_auth_event(
    db: AsyncSession,
    *,
    event_type: str,
    success: bool,
    user_id: UUID | None,
    subject_hash: str | None,
    ip_hash: str | None,
    user_agent_hash: str | None,
    details: dict[str, str] | None = None,
) -> None:
    record_auth_event(event_type, success)
    db.add(
        AuthEvent(
            event_type=event_type,
            success=success,
            user_id=user_id,
            subject_hash=subject_hash,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
            details=details or {},
        )
    )


def build_refresh_session(
    *, user_id: UUID, family_id: UUID | None, raw_token: str, request: Request, settings: Settings
) -> RefreshSession:
    ip_hash, user_agent_hash = request_fingerprints(request, settings)
    return RefreshSession(
        user_id=user_id,
        family_id=family_id or uuid4(),
        token_hash=token_digest(raw_token),
        expires_at=utc_now() + timedelta(days=settings.auth_refresh_token_days),
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
    )


async def revoke_family(
    db: AsyncSession, family_id: UUID, reason: str, revoked_at: datetime | None = None
) -> None:
    await db.execute(
        update(RefreshSession)
        .where(RefreshSession.family_id == family_id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=revoked_at or utc_now(), revoked_reason=reason)
    )


async def revoke_all_user_sessions(db: AsyncSession, user_id: UUID, reason: str) -> None:
    await db.execute(
        update(RefreshSession)
        .where(RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=utc_now(), revoked_reason=reason)
    )


async def consume_refresh_token(
    db: AsyncSession, raw_token: str, request: Request, settings: Settings
) -> tuple[RefreshSession, str]:
    now = utc_now()
    session = await db.scalar(
        select(RefreshSession)
        .where(RefreshSession.token_hash == token_digest(raw_token))
        .with_for_update()
    )
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh session.")

    if session.revoked_at is not None or session.replaced_by_id is not None:
        await revoke_family(db, session.family_id, "refresh_token_reuse", now)
        add_auth_event(
            db,
            event_type="refresh_reuse",
            success=False,
            user_id=session.user_id,
            subject_hash=None,
            ip_hash=session.ip_hash,
            user_agent_hash=session.user_agent_hash,
        )
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid or expired refresh session.")

    if as_utc(session.expires_at) <= now:
        session.revoked_at = now
        session.revoked_reason = "expired"
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid or expired refresh session.")

    replacement_token = new_refresh_token()
    replacement = build_refresh_session(
        user_id=session.user_id,
        family_id=session.family_id,
        raw_token=replacement_token,
        request=request,
        settings=settings,
    )
    replacement.expires_at = session.expires_at
    db.add(replacement)
    await db.flush()
    session.last_used_at = now
    session.revoked_at = now
    session.revoked_reason = "rotated"
    session.replaced_by_id = replacement.id
    return replacement, replacement_token
