import asyncio
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID
from weakref import WeakValueDictionary

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.passwords import hash_password, validate_password
from app.core.security import audit_fingerprint, token_digest
from app.models.auth import AuthEvent, AuthIdentity, TenantInvitation
from app.models.domain import MembershipRole, Tenant, TenantMembership, User
from app.schemas.members import (
    InvitationAcceptanceResponse,
    InvitationResponse,
    MemberListResponse,
    MemberResponse,
)
from app.services.auth import add_auth_event, as_utc, normalize_email, utc_now


class MemberAdministrationError(RuntimeError):
    pass


class MemberNotFoundError(MemberAdministrationError):
    pass


class MemberConflictError(MemberAdministrationError):
    pass


class FinalAdministratorError(MemberAdministrationError):
    pass


class InvitationNotFoundError(MemberAdministrationError):
    pass


class InvalidInvitationError(MemberAdministrationError):
    pass


class InvitationAuthenticationRequiredError(MemberAdministrationError):
    pass


class InvitationSetupRequiredError(MemberAdministrationError):
    pass


class InvitationRateLimitedError(MemberAdministrationError):
    pass


@dataclass(frozen=True)
class InvitationIssue:
    invitation: TenantInvitation
    tenant_name: str
    raw_token: str


_tenant_locks: WeakValueDictionary[UUID, asyncio.Lock] = WeakValueDictionary()
_invitation_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


def _lock_for_tenant(tenant_id: UUID) -> asyncio.Lock:
    lock = _tenant_locks.get(tenant_id)
    if lock is None:
        lock = asyncio.Lock()
        _tenant_locks[tenant_id] = lock
    return lock


def _lock_for_invitation(token_hash: str) -> asyncio.Lock:
    lock = _invitation_locks.get(token_hash)
    if lock is None:
        lock = asyncio.Lock()
        _invitation_locks[token_hash] = lock
    return lock


def _member_response(membership: TenantMembership, user: User) -> MemberResponse:
    return MemberResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=MembershipRole(membership.role),
        status="ACTIVE" if user.is_active else "INACTIVE",
        joined_at=membership.created_at,
    )


def _invitation_response(invitation: TenantInvitation) -> InvitationResponse:
    return InvitationResponse(
        id=invitation.id,
        email=invitation.email,
        role=MembershipRole(invitation.role),
        status="PENDING",
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
        invited_by_user_id=invitation.invited_by_user_id,
    )


async def _locked_tenant(db: AsyncSession, tenant_id: UUID) -> Tenant:
    tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if tenant is None or not tenant.is_active:
        raise MemberNotFoundError("Tenant not found.")
    return tenant


async def _active_admin_count(db: AsyncSession, tenant_id: UUID) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(TenantMembership)
        .join(User, User.id == TenantMembership.user_id)
        .where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.role == MembershipRole.ADMIN,
            User.is_active.is_(True),
        )
    )
    return count or 0


async def _member_by_id(
    db: AsyncSession, tenant_id: UUID, user_id: UUID, *, for_update: bool = False
) -> tuple[TenantMembership, User] | None:
    statement = (
        select(TenantMembership, User)
        .join(User, User.id == TenantMembership.user_id)
        .where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
        )
    )
    if for_update:
        statement = statement.with_for_update()
    return (await db.execute(statement)).one_or_none()


async def list_members(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    search: str,
    offset: int,
    limit: int,
) -> MemberListResponse:
    normalized_search = search.strip().casefold()
    member_filters = [TenantMembership.tenant_id == tenant_id]
    invitation_filters = [
        TenantInvitation.tenant_id == tenant_id,
        TenantInvitation.accepted_at.is_(None),
        TenantInvitation.revoked_at.is_(None),
        TenantInvitation.expires_at > utc_now(),
    ]
    if normalized_search:
        pattern = f"%{normalized_search}%"
        member_filters.append(
            or_(func.lower(User.email).like(pattern), func.lower(User.display_name).like(pattern))
        )
        invitation_filters.append(func.lower(TenantInvitation.email).like(pattern))

    total_members = await db.scalar(
        select(func.count())
        .select_from(TenantMembership)
        .join(User, User.id == TenantMembership.user_id)
        .where(*member_filters)
    )
    member_rows = (
        await db.execute(
            select(TenantMembership, User)
            .join(User, User.id == TenantMembership.user_id)
            .where(*member_filters)
            .order_by(User.display_name, User.email)
            .offset(offset)
            .limit(limit)
        )
    ).all()

    total_invitations = await db.scalar(
        select(func.count()).select_from(TenantInvitation).where(*invitation_filters)
    )
    invitations = list(
        await db.scalars(
            select(TenantInvitation)
            .where(*invitation_filters)
            .order_by(TenantInvitation.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return MemberListResponse(
        members=[_member_response(membership, user) for membership, user in member_rows],
        invitations=[_invitation_response(invitation) for invitation in invitations],
        total_members=total_members or 0,
        total_invitations=total_invitations or 0,
        offset=offset,
        limit=limit,
    )


async def _invitation_rate_limited(
    db: AsyncSession,
    *,
    actor_id: UUID,
    subject_hash: str,
    settings: Settings,
) -> bool:
    cutoff = utc_now() - timedelta(minutes=settings.tenant_invitation_resend_window_minutes)
    attempts = await db.scalar(
        select(func.count())
        .select_from(AuthEvent)
        .where(
            AuthEvent.event_type.in_(("tenant_invitation_created", "tenant_invitation_resent")),
            AuthEvent.success.is_(True),
            AuthEvent.user_id == actor_id,
            AuthEvent.subject_hash == subject_hash,
            AuthEvent.created_at >= cutoff,
        )
    )
    return (attempts or 0) >= settings.tenant_invitation_resend_limit


async def create_invitation(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    email: str,
    role: MembershipRole,
    settings: Settings,
    ip_hash: str,
    user_agent_hash: str,
) -> InvitationIssue:
    normalized_email = normalize_email(email)
    email_hash = audit_fingerprint(normalized_email, settings)
    async with _lock_for_tenant(tenant_id):
        tenant = await _locked_tenant(db, tenant_id)
        if await _invitation_rate_limited(
            db, actor_id=actor_id, subject_hash=email_hash, settings=settings
        ):
            add_auth_event(
                db,
                event_type="tenant_invitation_rate_limited",
                success=False,
                user_id=actor_id,
                subject_hash=email_hash,
                ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
                details={"tenant_id": str(tenant_id)},
            )
            await db.commit()
            raise InvitationRateLimitedError("Too many invitation emails. Try again later.")

        existing_member = await db.scalar(
            select(TenantMembership)
            .join(User, User.id == TenantMembership.user_id)
            .where(
                TenantMembership.tenant_id == tenant_id,
                func.lower(User.email) == normalized_email,
            )
        )
        if existing_member is not None:
            raise MemberConflictError("This user is already a member of the workspace.")

        now = utc_now()
        active_invitation = await db.scalar(
            select(TenantInvitation).where(
                TenantInvitation.tenant_id == tenant_id,
                TenantInvitation.email == normalized_email,
                TenantInvitation.accepted_at.is_(None),
                TenantInvitation.revoked_at.is_(None),
                TenantInvitation.expires_at > now,
            )
        )
        if active_invitation is not None:
            raise MemberConflictError("An active invitation already exists for this email.")

        raw_token = secrets.token_urlsafe(32)
        invitation = TenantInvitation(
            tenant_id=tenant_id,
            email=normalized_email,
            role=role,
            token_hash=token_digest(raw_token),
            invited_by_user_id=actor_id,
            expires_at=now + timedelta(hours=settings.tenant_invitation_hours),
        )
        db.add(invitation)
        await db.flush()
        add_auth_event(
            db,
            event_type="tenant_invitation_created",
            success=True,
            user_id=actor_id,
            subject_hash=email_hash,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
            details={
                "tenant_id": str(tenant_id),
                "invitation_id": str(invitation.id),
                "role": role.value,
            },
        )
        await db.commit()
        await db.refresh(invitation)
        return InvitationIssue(
            invitation=invitation,
            tenant_name=tenant.name,
            raw_token=raw_token,
        )


async def resend_invitation(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    invitation_id: UUID,
    actor_id: UUID,
    settings: Settings,
    ip_hash: str,
    user_agent_hash: str,
) -> InvitationIssue:
    async with _lock_for_tenant(tenant_id):
        tenant = await _locked_tenant(db, tenant_id)
        invitation = await db.scalar(
            select(TenantInvitation)
            .where(
                TenantInvitation.id == invitation_id,
                TenantInvitation.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if (
            invitation is None
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
        ):
            await _audit_missing_resource(
                db,
                actor_id=actor_id,
                tenant_id=tenant_id,
                resource_id=invitation_id,
                resource_type="invitation",
                ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
            )
            await db.commit()
            raise InvitationNotFoundError("Invitation not found.")

        email_hash = audit_fingerprint(invitation.email, settings)
        if await _invitation_rate_limited(
            db, actor_id=actor_id, subject_hash=email_hash, settings=settings
        ):
            add_auth_event(
                db,
                event_type="tenant_invitation_rate_limited",
                success=False,
                user_id=actor_id,
                subject_hash=email_hash,
                ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
                details={"tenant_id": str(tenant_id), "invitation_id": str(invitation.id)},
            )
            await db.commit()
            raise InvitationRateLimitedError("Too many invitation emails. Try again later.")

        raw_token = secrets.token_urlsafe(32)
        invitation.token_hash = token_digest(raw_token)
        invitation.expires_at = utc_now() + timedelta(hours=settings.tenant_invitation_hours)
        add_auth_event(
            db,
            event_type="tenant_invitation_resent",
            success=True,
            user_id=actor_id,
            subject_hash=email_hash,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
            details={"tenant_id": str(tenant_id), "invitation_id": str(invitation.id)},
        )
        await db.commit()
        await db.refresh(invitation)
        return InvitationIssue(invitation=invitation, tenant_name=tenant.name, raw_token=raw_token)


async def revoke_invitation(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    invitation_id: UUID,
    actor_id: UUID,
    settings: Settings,
    ip_hash: str,
    user_agent_hash: str,
) -> None:
    async with _lock_for_tenant(tenant_id):
        await _locked_tenant(db, tenant_id)
        invitation = await db.scalar(
            select(TenantInvitation)
            .where(
                TenantInvitation.id == invitation_id,
                TenantInvitation.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if (
            invitation is None
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
        ):
            await _audit_missing_resource(
                db,
                actor_id=actor_id,
                tenant_id=tenant_id,
                resource_id=invitation_id,
                resource_type="invitation",
                ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
            )
            await db.commit()
            raise InvitationNotFoundError("Invitation not found.")
        invitation.revoked_at = utc_now()
        add_auth_event(
            db,
            event_type="tenant_invitation_revoked",
            success=True,
            user_id=actor_id,
            subject_hash=audit_fingerprint(invitation.email, settings),
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
            details={"tenant_id": str(tenant_id), "invitation_id": str(invitation.id)},
        )
        await db.commit()


async def _audit_missing_resource(
    db: AsyncSession,
    *,
    actor_id: UUID,
    tenant_id: UUID,
    resource_id: UUID,
    resource_type: str,
    ip_hash: str,
    user_agent_hash: str,
) -> None:
    add_auth_event(
        db,
        event_type="tenant_resource_denied",
        success=False,
        user_id=actor_id,
        subject_hash=None,
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
        details={
            "tenant_id": str(tenant_id),
            "resource_id": str(resource_id),
            "resource_type": resource_type,
        },
    )


async def update_member_role(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    target_user_id: UUID,
    role: MembershipRole,
    actor_id: UUID,
    ip_hash: str,
    user_agent_hash: str,
) -> MemberResponse:
    async with _lock_for_tenant(tenant_id):
        await _locked_tenant(db, tenant_id)
        row = await _member_by_id(db, tenant_id, target_user_id, for_update=True)
        if row is None:
            await _audit_missing_resource(
                db,
                actor_id=actor_id,
                tenant_id=tenant_id,
                resource_id=target_user_id,
                resource_type="member",
                ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
            )
            await db.commit()
            raise MemberNotFoundError("Member not found.")
        membership, user = row
        old_role = MembershipRole(membership.role)
        if old_role == role:
            await db.commit()
            return _member_response(membership, user)
        if old_role == MembershipRole.ADMIN and role != MembershipRole.ADMIN:
            if await _active_admin_count(db, tenant_id) <= 1:
                add_auth_event(
                    db,
                    event_type="tenant_final_admin_denied",
                    success=False,
                    user_id=actor_id,
                    subject_hash=None,
                    ip_hash=ip_hash,
                    user_agent_hash=user_agent_hash,
                    details={
                        "tenant_id": str(tenant_id),
                        "target_user_id": str(target_user_id),
                        "operation": "role_change",
                    },
                )
                await db.commit()
                raise FinalAdministratorError("The final active administrator cannot be demoted.")
        membership.role = role
        add_auth_event(
            db,
            event_type="tenant_member_role_changed",
            success=True,
            user_id=actor_id,
            subject_hash=None,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
            details={
                "tenant_id": str(tenant_id),
                "target_user_id": str(target_user_id),
                "old_role": old_role.value,
                "new_role": role.value,
            },
        )
        await db.commit()
        await db.refresh(membership)
        return _member_response(membership, user)


async def remove_member(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    target_user_id: UUID,
    actor_id: UUID,
    ip_hash: str,
    user_agent_hash: str,
) -> None:
    async with _lock_for_tenant(tenant_id):
        await _locked_tenant(db, tenant_id)
        row = await _member_by_id(db, tenant_id, target_user_id, for_update=True)
        if row is None:
            await _audit_missing_resource(
                db,
                actor_id=actor_id,
                tenant_id=tenant_id,
                resource_id=target_user_id,
                resource_type="member",
                ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
            )
            await db.commit()
            raise MemberNotFoundError("Member not found.")
        membership, _ = row
        if MembershipRole(membership.role) == MembershipRole.ADMIN:
            if await _active_admin_count(db, tenant_id) <= 1:
                add_auth_event(
                    db,
                    event_type="tenant_final_admin_denied",
                    success=False,
                    user_id=actor_id,
                    subject_hash=None,
                    ip_hash=ip_hash,
                    user_agent_hash=user_agent_hash,
                    details={
                        "tenant_id": str(tenant_id),
                        "target_user_id": str(target_user_id),
                        "operation": "removal",
                    },
                )
                await db.commit()
                raise FinalAdministratorError("The final active administrator cannot be removed.")
        await db.delete(membership)
        add_auth_event(
            db,
            event_type="tenant_member_removed",
            success=True,
            user_id=actor_id,
            subject_hash=None,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
            details={"tenant_id": str(tenant_id), "target_user_id": str(target_user_id)},
        )
        await db.commit()


async def accept_invitation(
    db: AsyncSession,
    *,
    raw_token: str,
    current_user: User | None,
    display_name: str | None,
    password: str | None,
    settings: Settings,
    ip_hash: str,
    user_agent_hash: str,
) -> InvitationAcceptanceResponse:
    invitation_hash = token_digest(raw_token)
    initial = await db.scalar(
        select(TenantInvitation).where(TenantInvitation.token_hash == invitation_hash)
    )
    if initial is None:
        raise InvalidInvitationError("The invitation is invalid or has expired.")

    async with _lock_for_invitation(invitation_hash), _lock_for_tenant(initial.tenant_id):
        tenant = await _locked_tenant(db, initial.tenant_id)
        invitation = await db.scalar(
            select(TenantInvitation)
            .where(
                TenantInvitation.id == initial.id,
                TenantInvitation.token_hash == invitation_hash,
            )
            .with_for_update()
        )
        now = utc_now()
        if (
            invitation is None
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
            or as_utc(invitation.expires_at) <= now
        ):
            if invitation is not None:
                add_auth_event(
                    db,
                    event_type="tenant_invitation_accepted",
                    success=False,
                    user_id=current_user.id if current_user else None,
                    subject_hash=audit_fingerprint(invitation.email, settings),
                    ip_hash=ip_hash,
                    user_agent_hash=user_agent_hash,
                    details={
                        "tenant_id": str(invitation.tenant_id),
                        "invitation_id": str(invitation.id),
                    },
                )
                await db.commit()
            raise InvalidInvitationError("The invitation is invalid or has expired.")

        account_created = False
        user = current_user
        if user is None and settings.auth_mode == "oidc":
            add_auth_event(
                db,
                event_type="tenant_invitation_accepted",
                success=False,
                user_id=None,
                subject_hash=audit_fingerprint(invitation.email, settings),
                ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
                details={
                    "tenant_id": str(invitation.tenant_id),
                    "invitation_id": str(invitation.id),
                    "reason": "enterprise_sign_in_required",
                },
            )
            await db.commit()
            raise InvitationAuthenticationRequiredError(
                "Continue with enterprise sign-in to accept this invitation."
            )
        if user is not None:
            if normalize_email(user.email) != invitation.email:
                add_auth_event(
                    db,
                    event_type="tenant_invitation_accepted",
                    success=False,
                    user_id=user.id,
                    subject_hash=audit_fingerprint(invitation.email, settings),
                    ip_hash=ip_hash,
                    user_agent_hash=user_agent_hash,
                    details={
                        "tenant_id": str(invitation.tenant_id),
                        "invitation_id": str(invitation.id),
                        "reason": "identity_mismatch",
                    },
                )
                await db.commit()
                raise InvalidInvitationError("The invitation is invalid or has expired.")
        else:
            user = await db.scalar(select(User).where(func.lower(User.email) == invitation.email))
            if user is not None:
                add_auth_event(
                    db,
                    event_type="tenant_invitation_accepted",
                    success=False,
                    user_id=user.id,
                    subject_hash=audit_fingerprint(invitation.email, settings),
                    ip_hash=ip_hash,
                    user_agent_hash=user_agent_hash,
                    details={
                        "tenant_id": str(invitation.tenant_id),
                        "invitation_id": str(invitation.id),
                        "reason": "authentication_required",
                    },
                )
                await db.commit()
                raise InvitationAuthenticationRequiredError(
                    "Sign in with the invited account to accept this invitation."
                )
            if display_name is None or password is None:
                raise InvitationSetupRequiredError(
                    "Display name and password are required to create an account."
                )
            try:
                validate_password(password)
            except ValueError as exc:
                raise InvitationSetupRequiredError(str(exc)) from exc
            clean_name = display_name.strip()
            if not clean_name:
                raise InvitationSetupRequiredError("Display name is required.")
            user = User(
                external_subject=f"local:{invitation.email}",
                email=invitation.email,
                display_name=clean_name,
            )
            db.add(user)
            try:
                await db.flush()
            except IntegrityError as exc:
                await db.rollback()
                raise InvitationAuthenticationRequiredError(
                    "Sign in with the invited account to accept this invitation."
                ) from exc
            db.add(
                AuthIdentity(
                    user_id=user.id,
                    provider="local",
                    subject=invitation.email,
                    password_hash=hash_password(password),
                )
            )
            account_created = True

        membership = await db.get(TenantMembership, (invitation.tenant_id, user.id))
        if membership is None:
            membership = TenantMembership(
                tenant_id=invitation.tenant_id,
                user_id=user.id,
                role=invitation.role,
            )
            db.add(membership)
            effective_role = MembershipRole(invitation.role)
        else:
            effective_role = MembershipRole(membership.role)

        claimed = await db.execute(
            update(TenantInvitation)
            .where(
                TenantInvitation.id == invitation.id,
                TenantInvitation.token_hash == invitation_hash,
                TenantInvitation.accepted_at.is_(None),
                TenantInvitation.revoked_at.is_(None),
                TenantInvitation.expires_at > now,
            )
            .values(accepted_at=now, accepted_by_user_id=user.id)
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            await db.rollback()
            raise InvalidInvitationError("The invitation is invalid or has expired.")

        add_auth_event(
            db,
            event_type="tenant_invitation_accepted",
            success=True,
            user_id=user.id,
            subject_hash=audit_fingerprint(invitation.email, settings),
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
            details={
                "tenant_id": str(invitation.tenant_id),
                "invitation_id": str(invitation.id),
                "role": effective_role.value,
                "account_created": str(account_created).lower(),
            },
        )
        await db.commit()
        return InvitationAcceptanceResponse(
            message="Invitation accepted.",
            account_created=account_created,
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            role=effective_role,
        )


async def cleanup_tenant_invitations(db: AsyncSession, retention_days: int) -> int:
    cutoff = utc_now() - timedelta(days=retention_days)
    result = await db.execute(
        delete(TenantInvitation).where(
            or_(
                TenantInvitation.expires_at < cutoff,
                TenantInvitation.accepted_at < cutoff,
                TenantInvitation.revoked_at < cutoff,
            )
        )
    )
    await db.commit()
    return result.rowcount or 0
