from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import bearer, get_current_user
from app.core.config import Settings, get_settings
from app.core.passwords import hash_password, validate_password, verify_password
from app.core.security import (
    audit_fingerprint,
    create_access_token,
    decode_access_token,
    new_refresh_token,
    token_digest,
)
from app.db.session import get_db
from app.models.auth import AuthIdentity, PasswordResetToken, RefreshSession
from app.models.domain import User
from app.schemas.auth import (
    AuthMessageResponse,
    AuthSessionResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.services.auth import (
    add_auth_event,
    as_utc,
    build_refresh_session,
    clear_refresh_cookie,
    consume_refresh_token,
    enforce_trusted_origin,
    invalidate_unused_password_reset_tokens,
    login_is_rate_limited,
    new_password_reset_token,
    normalize_email,
    password_reset_is_rate_limited,
    request_fingerprints,
    revoke_all_user_sessions,
    revoke_family,
    set_refresh_cookie,
    utc_now,
)
from app.services.email import (
    TransactionalEmailProvider,
    build_password_reset_url,
    deliver_password_reset_email,
    get_email_provider,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
PASSWORD_RESET_ACCEPTED_MESSAGE = (
    "If the account is eligible, password reset instructions will be sent."
)
INVALID_RESET_TOKEN_MESSAGE = "The password reset link is invalid or has expired."


def _ensure_local_auth(settings: Settings) -> None:
    if settings.auth_mode not in {"local", "hybrid"}:
        raise HTTPException(status_code=404, detail="Local authentication is not enabled.")


def _ensure_internal_sessions(settings: Settings) -> None:
    if settings.auth_mode == "development":
        raise HTTPException(status_code=404, detail="Session authentication is not enabled.")


def _ensure_password_recovery(settings: Settings) -> None:
    _ensure_local_auth(settings)
    if not settings.password_recovery_enabled:
        raise HTTPException(status_code=404, detail="Password recovery is not enabled.")


def _access_response(user: User, family_id: UUID, settings: Settings) -> TokenResponse:
    access_token, expires_in = create_access_token(user.id, family_id, user.auth_version, settings)
    return TokenResponse(access_token=access_token, expires_in=expires_in)


async def _reject_password_reset(
    db: AsyncSession,
    *,
    user_id: UUID | None,
    ip_hash: str,
    user_agent_hash: str,
) -> None:
    add_auth_event(
        db,
        event_type="password_reset_completed",
        success=False,
        user_id=user_id,
        subject_hash=None,
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
    )
    await db.commit()
    raise HTTPException(status_code=400, detail=INVALID_RESET_TOKEN_MESSAGE)


@router.post(
    "/forgot-password",
    response_model=AuthMessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    email_provider: TransactionalEmailProvider = Depends(get_email_provider),
) -> AuthMessageResponse:
    _ensure_password_recovery(settings)
    enforce_trusted_origin(request, settings)
    email = normalize_email(str(payload.email))
    subject_hash = audit_fingerprint(email, settings)
    ip_hash, user_agent_hash = request_fingerprints(request, settings)

    if await password_reset_is_rate_limited(db, subject_hash, ip_hash, settings):
        add_auth_event(
            db,
            event_type="password_reset_rate_limited",
            success=False,
            user_id=None,
            subject_hash=subject_hash,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password reset requests. Try again later.",
            headers={"Retry-After": str(settings.password_reset_window_minutes * 60)},
        )

    identity = await db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == "local",
            AuthIdentity.subject == email,
        )
    )
    user = await db.get(User, identity.user_id) if identity is not None else None
    eligible = bool(
        identity is not None and identity.password_hash and user is not None and user.is_active
    )

    # Execute equivalent Argon2 work for eligible and ineligible requests.
    verify_password("password-reset-timing-probe", identity.password_hash if identity else None)

    add_auth_event(
        db,
        event_type="password_reset_requested",
        success=eligible,
        user_id=user.id if eligible and user else None,
        subject_hash=subject_hash,
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
    )

    if eligible and user is not None:
        now = utc_now()
        await invalidate_unused_password_reset_tokens(db, user.id, now)
        raw_token = new_password_reset_token()
        reset_token = PasswordResetToken(
            user_id=user.id,
            token_hash=token_digest(raw_token),
            expires_at=now + timedelta(minutes=settings.password_reset_minutes),
            requested_ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )
        db.add(reset_token)
        await db.flush()
        reset_url = build_password_reset_url(settings, raw_token)
        background_tasks.add_task(
            deliver_password_reset_email,
            email_provider,
            recipient=email,
            reset_url=reset_url,
            token_id=reset_token.id,
            user_id=user.id,
            subject_hash=subject_hash,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )

    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return AuthMessageResponse(message=PASSWORD_RESET_ACCEPTED_MESSAGE)


@router.post("/reset-password", response_model=AuthMessageResponse)
async def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthMessageResponse:
    _ensure_password_recovery(settings)
    enforce_trusted_origin(request, settings)
    new_password = payload.new_password.get_secret_value()
    try:
        validate_password(new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    new_password_hash = hash_password(new_password)

    now = utc_now()
    ip_hash, user_agent_hash = request_fingerprints(request, settings)
    reset_token = await db.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == token_digest(payload.token.get_secret_value()))
        .with_for_update()
    )
    if (
        reset_token is None
        or reset_token.used_at is not None
        or as_utc(reset_token.expires_at) <= now
    ):
        await _reject_password_reset(
            db,
            user_id=reset_token.user_id if reset_token else None,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )
        raise AssertionError("unreachable")

    user = await db.scalar(select(User).where(User.id == reset_token.user_id).with_for_update())
    identity = await db.scalar(
        select(AuthIdentity)
        .where(
            AuthIdentity.provider == "local",
            AuthIdentity.user_id == reset_token.user_id,
            AuthIdentity.password_hash.is_not(None),
        )
        .with_for_update()
    )
    if user is None or not user.is_active or identity is None:
        await _reject_password_reset(
            db,
            user_id=reset_token.user_id,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )
        raise AssertionError("unreachable")

    claimed = await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.id == reset_token.id,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        await _reject_password_reset(
            db,
            user_id=reset_token.user_id,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )
        raise AssertionError("unreachable")

    identity.password_hash = new_password_hash
    await invalidate_unused_password_reset_tokens(db, user.id, now)
    user.auth_version += 1
    await revoke_all_user_sessions(db, user.id, "password_reset")
    add_auth_event(
        db,
        event_type="password_reset_completed",
        success=True,
        user_id=user.id,
        subject_hash=None,
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
    )
    await db.commit()
    clear_refresh_cookie(response, settings)
    return AuthMessageResponse(message="Password reset complete. Sign in with your new password.")


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    _ensure_local_auth(settings)
    enforce_trusted_origin(request, settings)
    email = normalize_email(str(payload.email))
    password = payload.password.get_secret_value()
    subject_hash = audit_fingerprint(email, settings)
    ip_hash, user_agent_hash = request_fingerprints(request, settings)

    if await login_is_rate_limited(db, subject_hash, ip_hash, settings):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(settings.auth_login_window_minutes * 60)},
        )

    identity = await db.scalar(
        select(AuthIdentity).where(AuthIdentity.provider == "local", AuthIdentity.subject == email)
    )
    user = await db.get(User, identity.user_id) if identity else None
    valid_password = verify_password(password, identity.password_hash if identity else None)
    if not valid_password or user is None or not user.is_active:
        add_auth_event(
            db,
            event_type="login",
            success=False,
            user_id=user.id if user else None,
            subject_hash=subject_hash,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    raw_refresh_token = new_refresh_token()
    refresh_session = build_refresh_session(
        user_id=user.id,
        family_id=None,
        raw_token=raw_refresh_token,
        request=request,
        settings=settings,
    )
    identity.last_login_at = utc_now()
    db.add(refresh_session)
    add_auth_event(
        db,
        event_type="login",
        success=True,
        user_id=user.id,
        subject_hash=subject_hash,
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
    )
    await db.commit()
    set_refresh_cookie(response, raw_refresh_token, settings)
    return _access_response(user, refresh_session.family_id, settings)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    _ensure_internal_sessions(settings)
    enforce_trusted_origin(request, settings)
    raw_token = request.cookies.get(settings.auth_refresh_cookie_name)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Refresh session is required.")

    refresh_session, replacement_token = await consume_refresh_token(
        db, raw_token, request, settings
    )
    user = await db.get(User, refresh_session.user_id)
    if user is None or not user.is_active:
        await revoke_family(db, refresh_session.family_id, "user_inactive")
        await db.commit()
        clear_refresh_cookie(response, settings)
        raise HTTPException(status_code=401, detail="Invalid or expired refresh session.")

    ip_hash, user_agent_hash = request_fingerprints(request, settings)
    add_auth_event(
        db,
        event_type="refresh",
        success=True,
        user_id=user.id,
        subject_hash=None,
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
    )
    await db.commit()
    set_refresh_cookie(response, replacement_token, settings)
    return _access_response(user, refresh_session.family_id, settings)


@router.post("/logout", response_model=AuthMessageResponse)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthMessageResponse:
    _ensure_internal_sessions(settings)
    enforce_trusted_origin(request, settings)
    raw_token = request.cookies.get(settings.auth_refresh_cookie_name)
    if raw_token:
        refresh_session = await db.scalar(
            select(RefreshSession).where(RefreshSession.token_hash == token_digest(raw_token))
        )
        if refresh_session:
            await revoke_family(db, refresh_session.family_id, "logout")
            await db.commit()
    clear_refresh_cookie(response, settings)
    return AuthMessageResponse(message="Signed out.")


@router.post("/logout-all", response_model=AuthMessageResponse)
async def logout_all(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthMessageResponse:
    _ensure_internal_sessions(settings)
    enforce_trusted_origin(request, settings)
    user.auth_version += 1
    await revoke_all_user_sessions(db, user.id, "logout_all")
    ip_hash, user_agent_hash = request_fingerprints(request, settings)
    add_auth_event(
        db,
        event_type="logout_all",
        success=True,
        user_id=user.id,
        subject_hash=None,
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
    )
    await db.commit()
    clear_refresh_cookie(response, settings)
    return AuthMessageResponse(message="Signed out on all devices.")


@router.post("/change-password", response_model=AuthMessageResponse)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthMessageResponse:
    _ensure_local_auth(settings)
    enforce_trusted_origin(request, settings)
    identity = await db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == "local", AuthIdentity.user_id == user.id
        )
    )
    current_password = payload.current_password.get_secret_value()
    new_password = payload.new_password.get_secret_value()
    if identity is None or not verify_password(current_password, identity.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    try:
        validate_password(new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if verify_password(new_password, identity.password_hash):
        raise HTTPException(status_code=422, detail="New password must be different.")

    identity.password_hash = hash_password(new_password)
    user.auth_version += 1
    await revoke_all_user_sessions(db, user.id, "password_changed")
    ip_hash, user_agent_hash = request_fingerprints(request, settings)
    add_auth_event(
        db,
        event_type="password_changed",
        success=True,
        user_id=user.id,
        subject_hash=None,
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
    )
    await db.commit()
    clear_refresh_cookie(response, settings)
    return AuthMessageResponse(message="Password changed. Sign in again on each device.")


@router.get("/sessions", response_model=list[AuthSessionResponse])
async def list_sessions(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[AuthSessionResponse]:
    _ensure_internal_sessions(settings)
    if credentials is None:
        raise HTTPException(status_code=401, detail="Bearer access token is required.")
    token_identity = decode_access_token(credentials.credentials, settings)
    now = datetime.now(UTC)
    sessions = list(
        await db.scalars(
            select(RefreshSession)
            .where(
                RefreshSession.user_id == user.id,
                RefreshSession.revoked_at.is_(None),
                RefreshSession.expires_at > now,
            )
            .order_by(RefreshSession.created_at.desc())
        )
    )
    return [
        AuthSessionResponse(
            id=item.id,
            created_at=as_utc(item.created_at),
            last_used_at=as_utc(item.last_used_at) if item.last_used_at else None,
            expires_at=as_utc(item.expires_at),
            current=item.family_id == token_identity.session_family_id,
        )
        for item in sessions
    ]


@router.delete("/sessions/{session_id}", response_model=AuthMessageResponse)
async def revoke_session(
    session_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthMessageResponse:
    _ensure_internal_sessions(settings)
    enforce_trusted_origin(request, settings)
    refresh_session = await db.scalar(
        select(RefreshSession).where(
            RefreshSession.id == session_id, RefreshSession.user_id == user.id
        )
    )
    if refresh_session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    await revoke_family(db, refresh_session.family_id, "session_revoked")
    ip_hash, user_agent_hash = request_fingerprints(request, settings)
    add_auth_event(
        db,
        event_type="session_revoked",
        success=True,
        user_id=user.id,
        subject_hash=None,
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
        details={"session_id": str(refresh_session.id)},
    )
    await db.commit()
    return AuthMessageResponse(message="Session revoked.")
