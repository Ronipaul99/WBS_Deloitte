import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

import jwt
from fastapi import HTTPException, status

from app.core.config import Settings


@dataclass(frozen=True)
class OidcTokenIdentity:
    subject: str
    email: str
    display_name: str | None
    provider_tenant_id: str


class OidcTokenValidationError(ValueError):
    pass


@dataclass(frozen=True)
class AccessTokenIdentity:
    user_id: UUID
    session_family_id: UUID
    auth_version: int


def create_access_token(
    user_id: UUID, session_family_id: UUID, auth_version: int, settings: Settings
) -> tuple[str, int]:
    now = datetime.now(UTC)
    lifetime = (
        timedelta(seconds=settings.auth_access_token_seconds_override)
        if settings.auth_access_token_seconds_override is not None
        else timedelta(minutes=settings.auth_access_token_minutes)
    )
    token = jwt.encode(
        {
            "sub": str(user_id),
            "sid": str(session_family_id),
            "ver": auth_version,
            "jti": str(uuid4()),
            "type": "access",
            "iss": settings.auth_jwt_issuer,
            "aud": settings.auth_jwt_audience,
            "iat": now,
            "nbf": now,
            "exp": now + lifetime,
        },
        settings.auth_jwt_secret,
        algorithm="HS256",
    )
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str, settings: Settings) -> AccessTokenIdentity:
    try:
        claims = jwt.decode(
            token,
            settings.auth_jwt_secret,
            algorithms=["HS256"],
            audience=settings.auth_jwt_audience,
            issuer=settings.auth_jwt_issuer,
            options={"require": ["sub", "sid", "ver", "jti", "type", "exp", "iat", "nbf"]},
        )
        if claims["type"] != "access":
            raise jwt.InvalidTokenError("Unexpected token type")
        return AccessTokenIdentity(
            user_id=UUID(str(claims["sub"])),
            session_family_id=UUID(str(claims["sid"])),
            auth_version=int(claims["ver"]),
        )
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def token_digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def audit_fingerprint(value: str, settings: Settings) -> str:
    key = (settings.auth_audit_secret or settings.auth_jwt_secret).encode("utf-8")
    return hmac.new(key, value.encode("utf-8"), sha256).hexdigest()


def decode_oidc_id_token(
    token: str,
    jwks: dict[str, Any],
    expected_nonce: str,
    settings: Settings,
) -> OidcTokenIdentity:
    try:
        header = jwt.get_unverified_header(token)
        algorithm = str(header.get("alg", ""))
        key_id = str(header.get("kid", ""))
        if algorithm not in settings.oidc_algorithms or not key_id:
            raise OidcTokenValidationError("The ID token uses an unapproved signing key.")
        matching_keys = [
            key
            for key in jwks.get("keys", [])
            if str(key.get("kid", "")) == key_id
            and str(key.get("alg", algorithm)) == algorithm
            and key.get("use", "sig") == "sig"
            and ("key_ops" not in key or "verify" in key["key_ops"])
        ]
        if len(matching_keys) != 1:
            raise OidcTokenValidationError("The ID token signing key is unavailable.")
        matching_key = matching_keys[0]
        signing_key = jwt.PyJWK.from_dict(matching_key, algorithm=algorithm)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=settings.oidc_algorithms,
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            options={"require": ["iss", "aud", "sub", "exp", "iat", "nonce"]},
        )
        if not hmac.compare_digest(str(claims["nonce"]), expected_nonce):
            raise OidcTokenValidationError("The ID token nonce is invalid.")
        subject = str(claims["sub"]).strip()
        email = str(claims.get(settings.oidc_email_claim, "")).strip()
        tenant_id = str(claims.get(settings.oidc_tenant_claim, "")).strip()
        if not subject or not email or not tenant_id:
            raise OidcTokenValidationError("The ID token is missing required identity claims.")
        if claims.get(settings.oidc_email_verified_claim) is not True:
            raise OidcTokenValidationError("The provider has not verified this email address.")
        if settings.oidc_provider_tenant_id and not hmac.compare_digest(
            tenant_id, settings.oidc_provider_tenant_id
        ):
            raise OidcTokenValidationError("The identity belongs to an unapproved directory.")
        audience = claims["aud"]
        if (
            isinstance(audience, list)
            and len(audience) > 1
            and claims.get("azp") != settings.oidc_client_id
        ):
            raise OidcTokenValidationError("The ID token authorized party is invalid.")
        display_name = str(claims.get(settings.oidc_name_claim, "")).strip() or None
    except OidcTokenValidationError:
        raise
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise OidcTokenValidationError("The provider ID token is invalid or expired.") from exc

    return OidcTokenIdentity(
        subject=subject,
        email=email,
        display_name=display_name,
        provider_tenant_id=tenant_id,
    )
