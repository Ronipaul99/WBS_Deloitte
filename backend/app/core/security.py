from dataclasses import dataclass

import jwt
from fastapi import HTTPException, status
from jwt import PyJWKClient

from app.core.config import Settings


@dataclass(frozen=True)
class TokenIdentity:
    subject: str
    email: str | None
    display_name: str | None
    identity_tenant_id: str | None
    scopes: frozenset[str]


def decode_oidc_token(token: str, settings: Settings) -> TokenIdentity:
    if not settings.oidc_issuer or not settings.oidc_audience or not settings.oidc_jwks_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC authentication is enabled but not fully configured.",
        )

    try:
        signing_key = PyJWKClient(settings.oidc_jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=settings.oidc_algorithms,
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    subject = claims.get("sub") or claims.get("oid")
    if not subject:
        raise HTTPException(status_code=401, detail="Access token has no subject claim.")

    raw_scope = claims.get("scp") or claims.get("scope") or ""
    return TokenIdentity(
        subject=str(subject),
        email=claims.get("email") or claims.get("preferred_username"),
        display_name=claims.get("name"),
        identity_tenant_id=claims.get("tid"),
        scopes=frozenset(str(raw_scope).split()),
    )
