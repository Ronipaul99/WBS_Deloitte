import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from email_validator import EmailNotValidError, validate_email
from fastapi import Response
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import (
    OidcTokenIdentity,
    OidcTokenValidationError,
    audit_fingerprint,
    decode_oidc_id_token,
    token_digest,
)
from app.models.auth import AuthIdentity, OidcAuthorizationState, TenantInvitation
from app.models.domain import Tenant, TenantMembership, User
from app.services.auth import add_auth_event, as_utc, normalize_email, utc_now


class SsoError(RuntimeError):
    code = "sso_failed"


class SsoConfigurationError(SsoError):
    code = "provider_unavailable"


class SsoProtocolError(SsoError):
    code = "invalid_response"


class SsoStateError(SsoError):
    code = "invalid_state"


class SsoAccessDeniedError(SsoError):
    code = "access_denied"


class SsoIdentityConflictError(SsoError):
    code = "identity_conflict"


@dataclass(frozen=True)
class OidcMetadata:
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


@dataclass(frozen=True)
class SsoStartResult:
    authorization_url: str
    state_cookie: str


@dataclass(frozen=True)
class ConsumedSsoState:
    nonce: str
    pkce_verifier: str
    return_path: str


class OidcProvider(Protocol):
    async def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str: ...

    async def authenticate(
        self, *, code: str, pkce_verifier: str, nonce: str
    ) -> OidcTokenIdentity: ...


def _validate_provider_endpoint(value: Any, name: str, settings: Settings) -> str:
    if not isinstance(value, str):
        raise SsoConfigurationError(f"Provider metadata is missing {name}.")
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.netloc
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or (settings.app_env == "production" and parts.scheme != "https")
    ):
        raise SsoConfigurationError(f"Provider metadata contains an invalid {name}.")
    return value


class HttpOidcProvider:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    async def _get_json(self, url: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=10, follow_redirects=False, transport=self.transport
            ) as client:
                response = await client.get(url, headers={"Accept": "application/json"})
                response.raise_for_status()
                if len(response.content) > 1024 * 1024:
                    raise SsoConfigurationError("The identity provider response is too large.")
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SsoConfigurationError("The identity provider is unavailable.") from exc
        if not isinstance(body, dict):
            raise SsoConfigurationError("The identity provider returned invalid metadata.")
        return body

    async def _metadata(self) -> OidcMetadata:
        body = await self._get_json(self.settings.oidc_discovery_endpoint)
        if body.get("issuer") != self.settings.oidc_issuer:
            raise SsoConfigurationError(
                "The identity provider issuer does not match configuration."
            )
        endpoints = {
            "authorization_endpoint": _validate_provider_endpoint(
                body.get("authorization_endpoint"), "authorization_endpoint", self.settings
            ),
            "token_endpoint": _validate_provider_endpoint(
                body.get("token_endpoint"), "token_endpoint", self.settings
            ),
            "jwks_uri": _validate_provider_endpoint(
                body.get("jwks_uri"), "jwks_uri", self.settings
            ),
        }
        pins = {
            "authorization_endpoint": self.settings.oidc_authorization_endpoint,
            "token_endpoint": self.settings.oidc_token_endpoint,
            "jwks_uri": self.settings.oidc_jwks_url,
        }
        for name, pinned in pins.items():
            if pinned and endpoints[name] != pinned:
                raise SsoConfigurationError(
                    f"The discovered {name} does not match its configured pin."
                )
        return OidcMetadata(**endpoints)

    async def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        metadata = await self._metadata()
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.oidc_client_id,
                "redirect_uri": self.settings.oidc_redirect_uri,
                "scope": " ".join(self.settings.oidc_scope_list),
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{metadata.authorization_endpoint}?{query}"

    async def authenticate(self, *, code: str, pkce_verifier: str, nonce: str) -> OidcTokenIdentity:
        metadata = await self._metadata()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.oidc_redirect_uri,
            "code_verifier": pkce_verifier,
        }
        auth = None
        if self.settings.oidc_client_secret:
            auth = (self.settings.oidc_client_id or "", self.settings.oidc_client_secret)
        else:
            data["client_id"] = self.settings.oidc_client_id or ""
        try:
            async with httpx.AsyncClient(
                timeout=10, follow_redirects=False, transport=self.transport
            ) as client:
                response = await client.post(
                    metadata.token_endpoint,
                    data=data,
                    auth=auth,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                if len(response.content) > 1024 * 1024:
                    raise SsoProtocolError("The identity provider response is too large.")
                token_body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SsoProtocolError("The authorization code exchange failed.") from exc
        id_token = token_body.get("id_token") if isinstance(token_body, dict) else None
        if not isinstance(id_token, str) or not id_token:
            raise SsoProtocolError("The provider response did not contain an ID token.")
        jwks = await self._get_json(metadata.jwks_uri)
        try:
            return decode_oidc_id_token(id_token, jwks, nonce, self.settings)
        except OidcTokenValidationError as exc:
            raise SsoProtocolError(
                "The provider identity response could not be validated."
            ) from exc


def get_oidc_provider(settings: Settings) -> OidcProvider:
    return HttpOidcProvider(settings)


def _fernet(settings: Settings) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.oidc_state_secret.encode()).digest())
    return Fernet(key)


def _protect_state(state: str, nonce: str, verifier: str, settings: Settings) -> str:
    payload = json.dumps(
        {"state": state, "nonce": nonce, "verifier": verifier}, separators=(",", ":")
    ).encode()
    return _fernet(settings).encrypt(payload).decode()


def _open_state(cookie: str, state: str, settings: Settings) -> tuple[str, str]:
    try:
        payload = json.loads(
            _fernet(settings).decrypt(cookie.encode(), ttl=settings.oidc_state_minutes * 60)
        )
        if not secrets.compare_digest(str(payload["state"]), state):
            raise SsoStateError("The authorization state does not match this browser.")
        nonce = str(payload["nonce"])
        verifier = str(payload["verifier"])
        if len(nonce) < 32 or not 43 <= len(verifier) <= 128:
            raise SsoStateError("The authorization state is malformed.")
        return nonce, verifier
    except SsoStateError:
        raise
    except (InvalidToken, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SsoStateError("The authorization state is invalid or expired.") from exc


def set_sso_state_cookie(response: Response, value: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.oidc_state_cookie_name,
        value=value,
        max_age=settings.oidc_state_minutes * 60,
        path=f"{settings.api_v1_prefix}/auth/sso",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def clear_sso_state_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.oidc_state_cookie_name,
        path=f"{settings.api_v1_prefix}/auth/sso",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )


async def start_sso(
    db: AsyncSession,
    provider: OidcProvider,
    settings: Settings,
    return_path: str,
) -> SsoStartResult:
    if return_path not in settings.oidc_return_path_list:
        raise SsoStateError("The requested return path is not allowed.")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    authorization_url = await provider.authorization_url(
        state=state, nonce=nonce, code_challenge=challenge
    )
    db.add(
        OidcAuthorizationState(
            state_hash=token_digest(state),
            return_path=return_path,
            expires_at=utc_now() + timedelta(minutes=settings.oidc_state_minutes),
        )
    )
    await db.commit()
    return SsoStartResult(
        authorization_url=authorization_url,
        state_cookie=_protect_state(state, nonce, verifier, settings),
    )


async def consume_sso_state(
    db: AsyncSession,
    *,
    state: str,
    state_cookie: str | None,
    settings: Settings,
) -> ConsumedSsoState:
    if not state or not state_cookie:
        raise SsoStateError("The authorization state is missing.")
    nonce, verifier = _open_state(state_cookie, state, settings)
    now = utc_now()
    record = await db.scalar(
        select(OidcAuthorizationState)
        .where(OidcAuthorizationState.state_hash == token_digest(state))
        .with_for_update()
    )
    if record is None or record.consumed_at is not None or as_utc(record.expires_at) <= now:
        raise SsoStateError("The authorization state is invalid or expired.")
    claimed = await db.execute(
        update(OidcAuthorizationState)
        .where(
            OidcAuthorizationState.id == record.id,
            OidcAuthorizationState.consumed_at.is_(None),
            OidcAuthorizationState.expires_at > now,
        )
        .values(consumed_at=now)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        await db.rollback()
        raise SsoStateError("The authorization state has already been used.")
    await db.commit()
    return ConsumedSsoState(nonce=nonce, pkce_verifier=verifier, return_path=record.return_path)


def _identity_subject(identity: OidcTokenIdentity) -> str:
    namespaced = (
        f"{len(identity.provider_tenant_id)}:{identity.provider_tenant_id}:{identity.subject}"
    )
    if len(namespaced) <= 320:
        return namespaced
    return f"sha256:{hashlib.sha256(namespaced.encode()).hexdigest()}"


async def _has_active_membership(db: AsyncSession, user_id) -> bool:
    membership = await db.scalar(
        select(TenantMembership.user_id)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .where(TenantMembership.user_id == user_id, Tenant.is_active.is_(True))
        .limit(1)
    )
    return membership is not None


async def resolve_sso_user(
    db: AsyncSession,
    *,
    identity: OidcTokenIdentity,
    settings: Settings,
    ip_hash: str,
    user_agent_hash: str,
) -> tuple[User, AuthIdentity]:
    provider_subject = _identity_subject(identity)
    subject_hash = audit_fingerprint(f"{settings.oidc_provider_id}:{provider_subject}", settings)
    linked = await db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == settings.oidc_provider_id,
            AuthIdentity.subject == provider_subject,
        )
    )
    if linked is not None:
        user = await db.get(User, linked.user_id)
        if user is None or not user.is_active or not await _has_active_membership(db, user.id):
            add_auth_event(
                db,
                event_type="sso_login",
                success=False,
                user_id=user.id if user else None,
                subject_hash=subject_hash,
                ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
                details={"reason": "account_unavailable"},
            )
            await db.commit()
            raise SsoAccessDeniedError("This account is not provisioned for WBS Genie.")
        linked.last_login_at = utc_now()
        return user, linked

    try:
        normalized_email = normalize_email(
            validate_email(identity.email, check_deliverability=False).normalized
        )
    except EmailNotValidError as exc:
        raise SsoAccessDeniedError("This account is not provisioned for WBS Genie.") from exc

    now = utc_now()
    invitations = list(
        await db.scalars(
            select(TenantInvitation)
            .join(Tenant, Tenant.id == TenantInvitation.tenant_id)
            .where(
                func.lower(TenantInvitation.email) == normalized_email,
                TenantInvitation.accepted_at.is_(None),
                TenantInvitation.revoked_at.is_(None),
                TenantInvitation.expires_at > now,
                Tenant.is_active.is_(True),
            )
            .with_for_update()
        )
    )
    if not invitations:
        add_auth_event(
            db,
            event_type="sso_login",
            success=False,
            user_id=None,
            subject_hash=subject_hash,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
            details={"reason": "invitation_required"},
        )
        await db.commit()
        raise SsoAccessDeniedError("This account is not provisioned for WBS Genie.")

    user = await db.scalar(select(User).where(func.lower(User.email) == normalized_email))
    if user is not None and not user.is_active:
        raise SsoAccessDeniedError("This account is not provisioned for WBS Genie.")
    if user is None:
        user = User(
            external_subject=(
                "sso:"
                + hashlib.sha256(
                    f"{settings.oidc_provider_id}:{provider_subject}".encode()
                ).hexdigest()
            ),
            email=normalized_email,
            display_name=identity.display_name or normalized_email,
        )
        db.add(user)
        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            raise SsoIdentityConflictError(
                "This enterprise account is already being provisioned."
            ) from exc

    existing_provider_identity = await db.scalar(
        select(AuthIdentity.id).where(
            AuthIdentity.user_id == user.id,
            AuthIdentity.provider == settings.oidc_provider_id,
        )
    )
    if existing_provider_identity is not None:
        add_auth_event(
            db,
            event_type="sso_identity_linked",
            success=False,
            user_id=user.id,
            subject_hash=subject_hash,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
            details={"reason": "provider_identity_conflict"},
        )
        await db.commit()
        raise SsoIdentityConflictError(
            "This account is already linked to another provider identity."
        )

    linked = AuthIdentity(
        user_id=user.id,
        provider=settings.oidc_provider_id,
        subject=provider_subject,
        last_login_at=now,
    )
    db.add(linked)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise SsoIdentityConflictError("This provider identity is already linked.") from exc

    accepted_tenants: list[str] = []
    for invitation in invitations:
        membership = await db.get(TenantMembership, (invitation.tenant_id, user.id))
        if membership is None:
            db.add(
                TenantMembership(
                    tenant_id=invitation.tenant_id,
                    user_id=user.id,
                    role=invitation.role,
                )
            )
        claimed = await db.execute(
            update(TenantInvitation)
            .where(
                TenantInvitation.id == invitation.id,
                TenantInvitation.accepted_at.is_(None),
                TenantInvitation.revoked_at.is_(None),
                TenantInvitation.expires_at > now,
            )
            .values(accepted_at=now, accepted_by_user_id=user.id)
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            await db.rollback()
            raise SsoIdentityConflictError("The invitation was already consumed.")
        accepted_tenants.append(str(invitation.tenant_id))
        add_auth_event(
            db,
            event_type="tenant_invitation_accepted",
            success=True,
            user_id=user.id,
            subject_hash=audit_fingerprint(normalized_email, settings),
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
            details={
                "tenant_id": str(invitation.tenant_id),
                "invitation_id": str(invitation.id),
                "role": invitation.role,
                "account_created": "sso",
            },
        )
    add_auth_event(
        db,
        event_type="sso_identity_linked",
        success=True,
        user_id=user.id,
        subject_hash=subject_hash,
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
        details={
            "provider": settings.oidc_provider_id,
            "tenant_count": str(len(accepted_tenants)),
        },
    )
    return user, linked
