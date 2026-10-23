import base64
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.api.routes.sso import get_sso_provider
from app.core.config import Settings, get_settings
from app.core.security import OidcTokenIdentity, OidcTokenValidationError, decode_oidc_id_token
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import AuthIdentity, TenantInvitation
from app.models.domain import TenantMembership, User
from app.services.auth import utc_now
from app.services.sso import HttpOidcProvider, SsoProtocolError


class FakeOidcProvider:
    def __init__(self, identity: OidcTokenIdentity):
        self.identity = identity
        self.challenge = ""
        self.last_verifier = ""

    async def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        self.challenge = code_challenge
        return (
            "https://identity.example.test/authorize?"
            f"state={state}&nonce={nonce}&code_challenge={code_challenge}"
            "&code_challenge_method=S256&response_type=code"
        )

    async def authenticate(self, *, code: str, pkce_verifier: str, nonce: str) -> OidcTokenIdentity:
        assert code == "valid-code"
        assert len(nonce) >= 32
        self.last_verifier = pkce_verifier
        actual_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(pkce_verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        assert actual_challenge == self.challenge
        return self.identity


def sso_settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "auth_mode": "hybrid",
        "auth_jwt_secret": "test-only-secret-that-is-at-least-thirty-two-characters-long",
        "auth_audit_secret": "separate-test-only-audit-secret-that-is-also-long-enough",
        "oidc_state_secret": "independent-oidc-state-secret-that-is-long-enough",
        "oidc_issuer": "https://identity.example.test",
        "oidc_audience": "wbs-client",
        "oidc_client_id": "wbs-client",
        "oidc_client_secret": "test-client-secret",
        "oidc_redirect_uri": "http://testserver/api/v1/auth/sso/callback",
        "oidc_provider_tenant_id": "directory-1",
        "public_ui_url": "http://127.0.0.1:5173",
        "cors_origins": "http://127.0.0.1:5173",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def sso_client(client):
    settings = sso_settings()
    provider = FakeOidcProvider(
        OidcTokenIdentity(
            subject=f"subject-{uuid4().hex}",
            email=f"invited-{uuid4().hex}@example.com",
            display_name="Enterprise Planner",
            provider_tenant_id="directory-1",
        )
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_sso_provider] = lambda: provider
    client.cookies.clear()
    try:
        yield client, settings, provider
    finally:
        app.dependency_overrides.pop(get_sso_provider, None)
        app.dependency_overrides.pop(get_settings, None)


async def seed_invitation(email: str) -> TenantInvitation:
    invitation = TenantInvitation(
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        email=email.casefold(),
        role="EDITOR",
        token_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
        invited_by_user_id=UUID("00000000-0000-0000-0000-000000000001"),
        expires_at=utc_now() + timedelta(hours=1),
    )
    async with SessionLocal() as db:
        db.add(invitation)
        await db.commit()
        await db.refresh(invitation)
    return invitation


def begin_sso(client):
    response = client.get(
        "/api/v1/auth/sso/start?return_path=/sso/callback",
        follow_redirects=False,
    )
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    return response, query["state"][0]


def test_valid_pkce_flow_provisions_invited_user_and_issues_internal_session(sso_client):
    client, settings, provider = sso_client
    invitation = client.portal.call(seed_invitation, provider.identity.email)
    start, state = begin_sso(client)
    location = start.headers["location"]
    assert "code_challenge_method=S256" in location
    assert "response_type=code" in location
    assert settings.oidc_state_cookie_name in start.headers["set-cookie"]

    callback = client.get(
        f"/api/v1/auth/sso/callback?state={state}&code=valid-code",
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "http://127.0.0.1:5173/sso/callback"
    assert "access_token" not in callback.headers["location"]
    assert "id_token" not in callback.headers["location"]
    cookie = callback.headers["set-cookie"].lower()
    assert "wbs_refresh=" in cookie and "httponly" in cookie
    assert provider.last_verifier

    refreshed = client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    internal_token = refreshed.json()["access_token"]
    claims = jwt.decode(
        internal_token,
        settings.auth_jwt_secret,
        algorithms=["HS256"],
        audience=settings.auth_jwt_audience,
        issuer=settings.auth_jwt_issuer,
    )
    assert claims["type"] == "access"
    current_user = client.get("/api/v1/me", headers={"Authorization": f"Bearer {internal_token}"})
    assert current_user.status_code == 200
    assert settings.oidc_provider_id in current_user.json()["identity_providers"]

    async def invitation_was_consumed():
        async with SessionLocal() as db:
            stored = await db.get(TenantInvitation, invitation.id)
            return stored is not None and stored.accepted_at is not None

    assert client.portal.call(invitation_was_consumed)


def test_state_is_browser_bound_single_use_and_return_path_is_allowlisted(sso_client):
    client, settings, provider = sso_client
    unsafe = client.get(
        "/api/v1/auth/sso/start?return_path=https://attacker.example/callback",
        follow_redirects=False,
    )
    assert unsafe.status_code == 400

    client.portal.call(seed_invitation, provider.identity.email)
    _, state = begin_sso(client)
    state_cookie = client.cookies.get(settings.oidc_state_cookie_name)
    first = client.get(
        f"/api/v1/auth/sso/callback?state={state}&code=valid-code",
        follow_redirects=False,
    )
    assert first.status_code == 303

    client.cookies.set(
        settings.oidc_state_cookie_name,
        state_cookie,
        path="/api/v1/auth/sso",
    )
    replay = client.get(
        f"/api/v1/auth/sso/callback?state={state}&code=valid-code",
        follow_redirects=False,
    )
    assert replay.status_code == 303
    assert replay.headers["location"].endswith("/sso/callback?error=invalid_state")

    _, another_state = begin_sso(client)
    client.cookies.set(
        settings.oidc_state_cookie_name,
        "not-a-protected-cookie",
        path="/api/v1/auth/sso",
    )
    mismatch = client.get(
        f"/api/v1/auth/sso/callback?state={another_state}&code=valid-code",
        follow_redirects=False,
    )
    assert mismatch.headers["location"].endswith("?error=invalid_state")


def test_provider_error_consumes_state_and_uninvited_identity_is_denied(sso_client):
    client, settings, _ = sso_client
    _, state = begin_sso(client)
    provider_error = client.get(
        f"/api/v1/auth/sso/callback?state={state}&error=access_denied"
        "&error_description=secret-provider-detail",
        follow_redirects=False,
    )
    assert provider_error.headers["location"].endswith("?error=provider_denied")
    assert "secret-provider-detail" not in provider_error.headers["location"]

    _, state = begin_sso(client)
    denied = client.get(
        f"/api/v1/auth/sso/callback?state={state}&code=valid-code",
        follow_redirects=False,
    )
    assert denied.headers["location"].endswith("?error=access_denied")
    assert client.cookies.get(settings.auth_refresh_cookie_name) is None


def test_linked_identity_uses_database_membership_without_a_new_invitation(sso_client):
    client, settings, provider = sso_client

    async def seed_linked_identity():
        user = User(
            external_subject=f"linked-{uuid4().hex}",
            email=provider.identity.email,
            display_name="Linked User",
        )
        async with SessionLocal() as db:
            db.add(user)
            await db.flush()
            db.add_all(
                [
                    AuthIdentity(
                        user_id=user.id,
                        provider=settings.oidc_provider_id,
                        subject=(
                            f"{len(provider.identity.provider_tenant_id)}:"
                            f"{provider.identity.provider_tenant_id}:"
                            f"{provider.identity.subject}"
                        ),
                    ),
                    TenantMembership(
                        tenant_id=settings.dev_tenant_id,
                        user_id=user.id,
                        role="VIEWER",
                    ),
                ]
            )
            await db.commit()

    client.portal.call(seed_linked_identity)
    _, state = begin_sso(client)
    callback = client.get(
        f"/api/v1/auth/sso/callback?state={state}&code=valid-code",
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert "error=" not in callback.headers["location"]


def test_provider_directory_claim_never_grants_application_membership(sso_client):
    client, settings, provider = sso_client

    async def seed_identity_without_membership():
        user = User(
            external_subject=f"no-membership-{uuid4().hex}",
            email=provider.identity.email,
            display_name="No Membership",
        )
        async with SessionLocal() as db:
            db.add(user)
            await db.flush()
            db.add(
                AuthIdentity(
                    user_id=user.id,
                    provider=settings.oidc_provider_id,
                    subject=(
                        f"{len(provider.identity.provider_tenant_id)}:"
                        f"{provider.identity.provider_tenant_id}:"
                        f"{provider.identity.subject}"
                    ),
                )
            )
            await db.commit()

    client.portal.call(seed_identity_without_membership)
    _, state = begin_sso(client)
    callback = client.get(
        f"/api/v1/auth/sso/callback?state={state}&code=valid-code",
        follow_redirects=False,
    )
    assert callback.headers["location"].endswith("?error=access_denied")


def test_invitation_cannot_link_a_second_subject_for_the_same_provider(sso_client):
    client, settings, provider = sso_client

    async def seed_conflicting_identity():
        user = User(
            external_subject=f"provider-conflict-{uuid4().hex}",
            email=provider.identity.email,
            display_name="Already Linked User",
        )
        async with SessionLocal() as db:
            db.add(user)
            await db.flush()
            db.add(
                AuthIdentity(
                    user_id=user.id,
                    provider=settings.oidc_provider_id,
                    subject="11:directory-1:another-immutable-subject",
                )
            )
            await db.commit()

    client.portal.call(seed_conflicting_identity)
    client.portal.call(seed_invitation, provider.identity.email)
    _, state = begin_sso(client)
    callback = client.get(
        f"/api/v1/auth/sso/callback?state={state}&code=valid-code",
        follow_redirects=False,
    )
    assert callback.headers["location"].endswith("?error=identity_conflict")


def test_application_api_rejects_provider_bearer_tokens(sso_client):
    client, _, _ = sso_client
    provider_shaped_token = jwt.encode(
        {"sub": "external", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        "external-provider-secret-that-is-long-enough",
        algorithm="HS256",
    )
    response = client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {provider_shaped_token}"}
    )
    assert response.status_code == 401


def _rsa_material():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()

    def encode_int(value: int) -> str:
        length = (value.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(value.to_bytes(length, "big")).rstrip(b"=").decode()

    return private_key, {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": "key-1",
                "n": encode_int(public_numbers.n),
                "e": encode_int(public_numbers.e),
            }
        ]
    }


def _id_token(private_key, settings: Settings, **overrides) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_audience,
        "sub": "immutable-subject",
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "nonce": "expected-nonce",
        "email": "verified@example.com",
        "email_verified": True,
        "name": "Verified User",
        "tid": "directory-1",
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "key-1"})


@pytest.mark.parametrize(
    ("overrides", "nonce"),
    [
        ({"iss": "https://wrong-issuer.example"}, "expected-nonce"),
        ({"aud": "wrong-audience"}, "expected-nonce"),
        ({"exp": datetime.now(UTC) - timedelta(minutes=1)}, "expected-nonce"),
        ({"iat": datetime.now(UTC) + timedelta(minutes=5)}, "expected-nonce"),
        ({"nbf": datetime.now(UTC) + timedelta(minutes=5)}, "expected-nonce"),
        ({"email_verified": False}, "expected-nonce"),
        ({}, "wrong-nonce"),
        ({"tid": "unapproved-directory"}, "expected-nonce"),
    ],
)
def test_id_token_validation_rejects_untrusted_claims(overrides, nonce):
    settings = sso_settings()
    private_key, jwks = _rsa_material()
    with pytest.raises(OidcTokenValidationError):
        decode_oidc_id_token(_id_token(private_key, settings, **overrides), jwks, nonce, settings)


def test_id_token_validation_accepts_pinned_signature_claims_and_nonce():
    settings = sso_settings()
    private_key, jwks = _rsa_material()
    identity = decode_oidc_id_token(
        _id_token(private_key, settings), jwks, "expected-nonce", settings
    )
    assert identity.subject == "immutable-subject"
    assert identity.email == "verified@example.com"
    assert identity.provider_tenant_id == "directory-1"


def test_multiple_id_token_audiences_require_the_registered_client_as_azp():
    settings = sso_settings()
    private_key, jwks = _rsa_material()
    audiences = [settings.oidc_audience, "another-audience"]
    with pytest.raises(OidcTokenValidationError):
        decode_oidc_id_token(
            _id_token(private_key, settings, aud=audiences),
            jwks,
            "expected-nonce",
            settings,
        )
    identity = decode_oidc_id_token(
        _id_token(
            private_key,
            settings,
            aud=audiences,
            azp=settings.oidc_client_id,
        ),
        jwks,
        "expected-nonce",
        settings,
    )
    assert identity.subject == "immutable-subject"


def test_id_token_validation_rejects_invalid_signature_and_algorithm():
    settings = sso_settings()
    trusted_private_key, trusted_jwks = _rsa_material()
    untrusted_private_key, _ = _rsa_material()
    del trusted_private_key
    with pytest.raises(OidcTokenValidationError):
        decode_oidc_id_token(
            _id_token(untrusted_private_key, settings),
            trusted_jwks,
            "expected-nonce",
            settings,
        )

    now = datetime.now(UTC)
    symmetric_token = jwt.encode(
        {
            "iss": settings.oidc_issuer,
            "aud": settings.oidc_audience,
            "sub": "subject",
            "exp": now + timedelta(minutes=5),
            "iat": now,
            "nonce": "expected-nonce",
            "email": "verified@example.com",
            "email_verified": True,
            "tid": "directory-1",
        },
        "a-symmetric-test-key-that-is-long-enough",
        algorithm="HS256",
        headers={"kid": "key-1"},
    )
    with pytest.raises(OidcTokenValidationError):
        decode_oidc_id_token(symmetric_token, trusted_jwks, "expected-nonce", settings)


def test_id_token_validation_accepts_a_rotated_signing_key_set():
    settings = sso_settings()
    rotated_private_key, rotated_jwks = _rsa_material()
    identity = decode_oidc_id_token(
        _id_token(rotated_private_key, settings),
        rotated_jwks,
        "expected-nonce",
        settings,
    )
    assert identity.subject == "immutable-subject"


async def test_http_provider_uses_discovery_basic_client_auth_pkce_and_jwks():
    settings = sso_settings()
    private_key, jwks = _rsa_material()
    expected_verifier = "v" * 64
    nonce = "n" * 43

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": settings.oidc_issuer,
                    "authorization_endpoint": "https://identity.example.test/authorize",
                    "token_endpoint": "https://identity.example.test/token",
                    "jwks_uri": "https://identity.example.test/jwks",
                },
            )
        if request.url.path == "/token":
            form = parse_qs(request.content.decode())
            assert request.headers["authorization"].startswith("Basic ")
            assert "client_secret" not in form
            if form.get("code_verifier") != [expected_verifier]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            assert form["code"] == ["valid-code"]
            assert form["grant_type"] == ["authorization_code"]
            return httpx.Response(
                200,
                json={"id_token": _id_token(private_key, settings, nonce=nonce)},
            )
        if request.url.path == "/jwks":
            return httpx.Response(200, json=jwks)
        raise AssertionError(f"Unexpected provider request: {request.url}")

    provider = HttpOidcProvider(settings, transport=httpx.MockTransport(handler))
    authorization_url = await provider.authorization_url(
        state="s" * 43,
        nonce=nonce,
        code_challenge="c" * 43,
    )
    authorization_query = parse_qs(urlsplit(authorization_url).query)
    assert authorization_query["code_challenge_method"] == ["S256"]
    assert authorization_query["redirect_uri"] == [settings.oidc_redirect_uri]

    identity = await provider.authenticate(
        code="valid-code",
        pkce_verifier=expected_verifier,
        nonce=nonce,
    )
    assert identity.email == "verified@example.com"

    with pytest.raises(SsoProtocolError):
        await provider.authenticate(
            code="valid-code",
            pkce_verifier="x" * 64,
            nonce=nonce,
        )
