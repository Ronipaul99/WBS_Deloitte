from datetime import timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import audit_fingerprint, new_refresh_token
from app.db.session import get_db
from app.models.auth import AuthEvent
from app.services.auth import (
    add_auth_event,
    build_refresh_session,
    request_fingerprints,
    set_refresh_cookie,
    utc_now,
)
from app.services.sso import (
    OidcProvider,
    SsoAccessDeniedError,
    SsoConfigurationError,
    SsoError,
    SsoIdentityConflictError,
    SsoProtocolError,
    SsoStateError,
    clear_sso_state_cookie,
    consume_sso_state,
    get_oidc_provider,
    resolve_sso_user,
    set_sso_state_cookie,
    start_sso,
)

router = APIRouter(prefix="/auth/sso", tags=["authentication"])


def get_sso_provider(settings: Settings = Depends(get_settings)) -> OidcProvider:
    return get_oidc_provider(settings)


def _ensure_sso(settings: Settings) -> None:
    if settings.auth_mode not in {"oidc", "hybrid"}:
        raise HTTPException(status_code=404, detail="Enterprise sign-in is not enabled.")


def _ui_redirect(settings: Settings, return_path: str, error: str | None = None) -> str:
    path = return_path if return_path in settings.oidc_return_path_list else "/sso/callback"
    target = f"{(settings.public_ui_url or '').rstrip('/')}{path}"
    return f"{target}?{urlencode({'error': error})}" if error else target


async def _audit_failure(
    db: AsyncSession,
    request: Request,
    settings: Settings,
    *,
    reason: str,
    state: str | None,
) -> None:
    ip_hash, user_agent_hash = request_fingerprints(request, settings)
    add_auth_event(
        db,
        event_type="sso_login",
        success=False,
        user_id=None,
        subject_hash=audit_fingerprint(state, settings) if state else None,
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
        details={"reason": reason},
    )
    await db.commit()


async def _start_is_rate_limited(db: AsyncSession, ip_hash: str, settings: Settings) -> bool:
    cutoff = utc_now() - timedelta(minutes=settings.auth_login_window_minutes)
    attempts = await db.scalar(
        select(func.count())
        .select_from(AuthEvent)
        .where(
            AuthEvent.event_type == "sso_start",
            AuthEvent.ip_hash == ip_hash,
            AuthEvent.created_at >= cutoff,
        )
    )
    return (attempts or 0) >= settings.auth_login_ip_limit


def _error_redirect(settings: Settings, return_path: str, code: str) -> RedirectResponse:
    response = RedirectResponse(_ui_redirect(settings, return_path, code), status_code=303)
    clear_sso_state_cookie(response, settings)
    return response


@router.get("/start", status_code=status.HTTP_302_FOUND)
async def begin_enterprise_sign_in(
    request: Request,
    return_path: str = Query(default="/sso/callback", max_length=255),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    provider: OidcProvider = Depends(get_sso_provider),
) -> RedirectResponse:
    _ensure_sso(settings)
    ip_hash, user_agent_hash = request_fingerprints(request, settings)
    if await _start_is_rate_limited(db, ip_hash, settings):
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in attempts. Try again later.",
            headers={"Retry-After": str(settings.auth_login_window_minutes * 60)},
        )
    try:
        result = await start_sso(db, provider, settings, return_path)
    except SsoStateError as exc:
        raise HTTPException(status_code=400, detail="The return path is not allowed.") from exc
    except SsoConfigurationError as exc:
        add_auth_event(
            db,
            event_type="sso_start",
            success=False,
            user_id=None,
            subject_hash=None,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
            details={"reason": "provider_unavailable"},
        )
        await db.commit()
        raise HTTPException(
            status_code=503, detail="Enterprise sign-in is temporarily unavailable."
        ) from exc
    add_auth_event(
        db,
        event_type="sso_start",
        success=True,
        user_id=None,
        subject_hash=None,
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
    )
    await db.commit()
    response = RedirectResponse(result.authorization_url, status_code=302)
    set_sso_state_cookie(response, result.state_cookie, settings)
    return response


@router.get("/callback")
async def complete_enterprise_sign_in(
    request: Request,
    state: str = Query(default="", max_length=512),
    code: str | None = Query(default=None, max_length=4096),
    error: str | None = Query(default=None, max_length=200),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    provider: OidcProvider = Depends(get_sso_provider),
) -> RedirectResponse:
    _ensure_sso(settings)
    default_path = "/sso/callback"
    try:
        transaction = await consume_sso_state(
            db,
            state=state,
            state_cookie=request.cookies.get(settings.oidc_state_cookie_name),
            settings=settings,
        )
    except SsoStateError:
        await _audit_failure(db, request, settings, reason="invalid_state", state=state or None)
        return _error_redirect(settings, default_path, "invalid_state")

    if error:
        await _audit_failure(db, request, settings, reason="provider_denied", state=state)
        return _error_redirect(settings, transaction.return_path, "provider_denied")
    if not code:
        await _audit_failure(db, request, settings, reason="missing_code", state=state)
        return _error_redirect(settings, transaction.return_path, "invalid_response")

    try:
        provider_identity = await provider.authenticate(
            code=code,
            pkce_verifier=transaction.pkce_verifier,
            nonce=transaction.nonce,
        )
        ip_hash, user_agent_hash = request_fingerprints(request, settings)
        user, identity = await resolve_sso_user(
            db,
            identity=provider_identity,
            settings=settings,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )
        raw_refresh_token = new_refresh_token()
        refresh_session = build_refresh_session(
            user_id=user.id,
            family_id=None,
            raw_token=raw_refresh_token,
            request=request,
            settings=settings,
        )
        db.add(refresh_session)
        add_auth_event(
            db,
            event_type="sso_login",
            success=True,
            user_id=user.id,
            subject_hash=audit_fingerprint(f"{identity.provider}:{identity.subject}", settings),
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
            details={"provider": identity.provider},
        )
        await db.commit()
    except SsoConfigurationError:
        await _audit_failure(db, request, settings, reason="provider_unavailable", state=state)
        return _error_redirect(settings, transaction.return_path, "provider_unavailable")
    except SsoProtocolError:
        await _audit_failure(db, request, settings, reason="invalid_response", state=state)
        return _error_redirect(settings, transaction.return_path, "invalid_response")
    except SsoAccessDeniedError:
        return _error_redirect(settings, transaction.return_path, "access_denied")
    except SsoIdentityConflictError:
        await _audit_failure(db, request, settings, reason="identity_conflict", state=state)
        return _error_redirect(settings, transaction.return_path, "identity_conflict")
    except SsoError:
        await _audit_failure(db, request, settings, reason="sso_failed", state=state)
        return _error_redirect(settings, transaction.return_path, "sso_failed")

    response = RedirectResponse(_ui_redirect(settings, transaction.return_path), status_code=303)
    clear_sso_state_cookie(response, settings)
    set_refresh_cookie(response, raw_refresh_token, settings)
    return response
