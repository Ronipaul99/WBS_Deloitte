import re
from dataclasses import dataclass
from uuid import UUID

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.passwords import hash_password
from app.models.auth import AuthIdentity
from app.models.domain import MembershipRole, Tenant, TenantMembership, User
from app.services.auth import normalize_email

_EMAIL_ADAPTER = TypeAdapter(EmailStr)
_TENANT_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class AdminProvisioningError(ValueError):
    """An expected, operator-safe first-admin provisioning failure."""


@dataclass(frozen=True)
class ProvisionedAdministrator:
    user_id: UUID
    tenant_id: UUID
    email: str
    tenant_slug: str


def _validated_email(value: str) -> str:
    try:
        return normalize_email(str(_EMAIL_ADAPTER.validate_python(value)))
    except ValidationError as exc:
        raise AdminProvisioningError("Enter a valid administrator email address.") from exc


def _validated_text(value: str, field_name: str, maximum_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise AdminProvisioningError(f"{field_name} is required.")
    if len(normalized) > maximum_length:
        raise AdminProvisioningError(f"{field_name} must not exceed {maximum_length} characters.")
    return normalized


def _validated_tenant_slug(value: str) -> str:
    slug = value.strip().casefold()
    if len(slug) > 80 or not _TENANT_SLUG_PATTERN.fullmatch(slug):
        raise AdminProvisioningError(
            "Tenant slug must contain only lowercase letters, numbers, and single hyphens."
        )
    return slug


async def provision_local_administrator(
    db: AsyncSession,
    *,
    email: str,
    display_name: str,
    tenant_slug: str,
    tenant_name: str,
    password: str,
    link_existing_user: bool = False,
) -> ProvisionedAdministrator:
    """Create the first local administrator as one atomic database transaction."""

    normalized_email = _validated_email(email)
    normalized_display_name = _validated_text(display_name, "Display name", 160)
    normalized_tenant_name = _validated_text(tenant_name, "Tenant name", 160)
    normalized_tenant_slug = _validated_tenant_slug(tenant_slug)

    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        raise AdminProvisioningError(str(exc)) from exc

    try:
        async with db.begin():
            identity = await db.scalar(
                select(AuthIdentity).where(
                    AuthIdentity.provider == "local",
                    AuthIdentity.subject == normalized_email,
                )
            )
            if identity is not None:
                raise AdminProvisioningError(
                    "A local identity already exists for that email address."
                )

            tenant = await db.scalar(select(Tenant).where(Tenant.slug == normalized_tenant_slug))
            if tenant is None:
                tenant = Tenant(name=normalized_tenant_name, slug=normalized_tenant_slug)
                db.add(tenant)
                await db.flush()
            elif not tenant.is_active:
                raise AdminProvisioningError("The requested tenant is inactive.")

            user = await db.scalar(select(User).where(User.email == normalized_email))
            if user is None:
                user = User(
                    external_subject=f"local:{normalized_email}",
                    email=normalized_email,
                    display_name=normalized_display_name,
                )
                db.add(user)
                await db.flush()
            else:
                if not link_existing_user:
                    raise AdminProvisioningError(
                        "A user already exists for that email address. Re-run with "
                        "--link-existing-user after verifying the account."
                    )
                if not user.is_active:
                    raise AdminProvisioningError("The existing user is inactive.")
                user_identity = await db.scalar(
                    select(AuthIdentity).where(
                        AuthIdentity.provider == "local",
                        AuthIdentity.user_id == user.id,
                    )
                )
                if user_identity is not None:
                    raise AdminProvisioningError("The existing user already has a local identity.")

            db.add(
                AuthIdentity(
                    user_id=user.id,
                    provider="local",
                    subject=normalized_email,
                    password_hash=password_hash,
                )
            )
            membership = await db.get(TenantMembership, (tenant.id, user.id))
            if membership is None:
                db.add(
                    TenantMembership(
                        tenant_id=tenant.id,
                        user_id=user.id,
                        role=MembershipRole.ADMIN,
                    )
                )
            else:
                membership.role = MembershipRole.ADMIN

            await db.flush()
            result = ProvisionedAdministrator(
                user_id=user.id,
                tenant_id=tenant.id,
                email=normalized_email,
                tenant_slug=tenant.slug,
            )
    except IntegrityError as exc:
        raise AdminProvisioningError(
            "Administrator provisioning conflicted with existing data; no changes were saved."
        ) from exc

    return result
