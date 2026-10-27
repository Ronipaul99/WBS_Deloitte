from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authorization import TENANT_AUTH_RESPONSES, require_permission
from app.api.dependencies import TenantContext, get_optional_current_user
from app.core.config import Settings, get_settings
from app.core.permissions import Permission
from app.core.security import audit_fingerprint
from app.db.session import get_db
from app.models.domain import User
from app.schemas.members import (
    InvitationAcceptanceRequest,
    InvitationAcceptanceResponse,
    InvitationCreateRequest,
    InvitationResponse,
    MemberListResponse,
    MemberResponse,
    MembershipRoleUpdateRequest,
)
from app.services.auth import enforce_trusted_origin, request_fingerprints
from app.services.email import (
    TransactionalEmailProvider,
    build_tenant_invitation_url,
    deliver_tenant_invitation_email,
    get_email_provider,
)
from app.services.members import (
    FinalAdministratorError,
    InvalidInvitationError,
    InvitationAuthenticationRequiredError,
    InvitationNotFoundError,
    InvitationRateLimitedError,
    InvitationSetupRequiredError,
    MemberConflictError,
    MemberNotFoundError,
    accept_invitation,
    create_invitation,
    list_members,
    remove_member,
    resend_invitation,
    revoke_invitation,
    update_member_role,
)

router = APIRouter(tags=["tenant members"])


def _ensure_invitations_enabled(settings: Settings) -> None:
    if not settings.tenant_invitations_enabled:
        raise HTTPException(status_code=404, detail="Tenant invitations are not enabled.")


def _invitation_response(issue) -> InvitationResponse:
    invitation = issue.invitation
    return InvitationResponse(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        status="PENDING",
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
        invited_by_user_id=invitation.invited_by_user_id,
    )


@router.get(
    "/tenants/{tenant_id}/members",
    response_model=MemberListResponse,
    responses=TENANT_AUTH_RESPONSES,
)
async def get_tenant_members(
    search: str = Query(default="", max_length=120),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    context: TenantContext = Depends(require_permission(Permission.MEMBER_READ)),
    db: AsyncSession = Depends(get_db),
) -> MemberListResponse:
    return await list_members(
        db,
        context.tenant.id,
        search=search,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/tenants/{tenant_id}/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    responses=TENANT_AUTH_RESPONSES,
)
async def invite_tenant_member(
    payload: InvitationCreateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    context: TenantContext = Depends(require_permission(Permission.MEMBER_INVITE)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    email_provider: TransactionalEmailProvider = Depends(get_email_provider),
) -> InvitationResponse:
    _ensure_invitations_enabled(settings)
    enforce_trusted_origin(request, settings)
    ip_hash, user_agent_hash = request_fingerprints(request, settings)
    try:
        issue = await create_invitation(
            db,
            tenant_id=context.tenant.id,
            actor_id=context.user.id,
            email=str(payload.email),
            role=payload.role,
            settings=settings,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )
    except MemberConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvitationRateLimitedError as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(settings.tenant_invitation_resend_window_minutes * 60)},
        ) from exc

    background_tasks.add_task(
        deliver_tenant_invitation_email,
        email_provider,
        recipient=issue.invitation.email,
        invitation_url=build_tenant_invitation_url(settings, issue.raw_token),
        tenant_name=issue.tenant_name,
        invitation_id=issue.invitation.id,
        actor_id=context.user.id,
        subject_hash=audit_fingerprint(issue.invitation.email, settings),
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
    )
    return _invitation_response(issue)


@router.post(
    "/tenants/{tenant_id}/invitations/{invitation_id}/resend",
    response_model=InvitationResponse,
    responses=TENANT_AUTH_RESPONSES,
)
async def resend_tenant_invitation(
    invitation_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    context: TenantContext = Depends(require_permission(Permission.MEMBER_INVITE)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    email_provider: TransactionalEmailProvider = Depends(get_email_provider),
) -> InvitationResponse:
    _ensure_invitations_enabled(settings)
    enforce_trusted_origin(request, settings)
    ip_hash, user_agent_hash = request_fingerprints(request, settings)
    try:
        issue = await resend_invitation(
            db,
            tenant_id=context.tenant.id,
            invitation_id=invitation_id,
            actor_id=context.user.id,
            settings=settings,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )
    except InvitationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Invitation not found.") from exc
    except InvitationRateLimitedError as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(settings.tenant_invitation_resend_window_minutes * 60)},
        ) from exc

    background_tasks.add_task(
        deliver_tenant_invitation_email,
        email_provider,
        recipient=issue.invitation.email,
        invitation_url=build_tenant_invitation_url(settings, issue.raw_token),
        tenant_name=issue.tenant_name,
        invitation_id=issue.invitation.id,
        actor_id=context.user.id,
        subject_hash=audit_fingerprint(issue.invitation.email, settings),
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
    )
    return _invitation_response(issue)


@router.delete(
    "/tenants/{tenant_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=TENANT_AUTH_RESPONSES,
)
async def delete_tenant_invitation(
    invitation_id: UUID,
    request: Request,
    context: TenantContext = Depends(require_permission(Permission.MEMBER_INVITE)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    _ensure_invitations_enabled(settings)
    enforce_trusted_origin(request, settings)
    ip_hash, user_agent_hash = request_fingerprints(request, settings)
    try:
        await revoke_invitation(
            db,
            tenant_id=context.tenant.id,
            invitation_id=invitation_id,
            actor_id=context.user.id,
            settings=settings,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )
    except InvitationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Invitation not found.") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/tenants/{tenant_id}/members/{user_id}",
    response_model=MemberResponse,
    responses=TENANT_AUTH_RESPONSES,
)
async def change_tenant_member_role(
    user_id: UUID,
    payload: MembershipRoleUpdateRequest,
    request: Request,
    context: TenantContext = Depends(require_permission(Permission.MEMBER_UPDATE)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MemberResponse:
    enforce_trusted_origin(request, settings)
    ip_hash, user_agent_hash = request_fingerprints(request, settings)
    try:
        return await update_member_role(
            db,
            tenant_id=context.tenant.id,
            target_user_id=user_id,
            role=payload.role,
            actor_id=context.user.id,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )
    except MemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Member not found.") from exc
    except FinalAdministratorError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete(
    "/tenants/{tenant_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=TENANT_AUTH_RESPONSES,
)
async def delete_tenant_member(
    user_id: UUID,
    request: Request,
    context: TenantContext = Depends(require_permission(Permission.MEMBER_REMOVE)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    enforce_trusted_origin(request, settings)
    ip_hash, user_agent_hash = request_fingerprints(request, settings)
    try:
        await remove_member(
            db,
            tenant_id=context.tenant.id,
            target_user_id=user_id,
            actor_id=context.user.id,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )
    except MemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Member not found.") from exc
    except FinalAdministratorError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/auth/accept-invitation",
    response_model=InvitationAcceptanceResponse,
)
async def accept_tenant_invitation(
    payload: InvitationAcceptanceRequest,
    request: Request,
    current_user: User | None = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> InvitationAcceptanceResponse:
    _ensure_invitations_enabled(settings)
    enforce_trusted_origin(request, settings)
    ip_hash, user_agent_hash = request_fingerprints(request, settings)
    try:
        return await accept_invitation(
            db,
            raw_token=payload.token.get_secret_value(),
            current_user=current_user,
            display_name=payload.display_name,
            password=payload.password.get_secret_value() if payload.password else None,
            settings=settings,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )
    except InvalidInvitationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvitationAuthenticationRequiredError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except InvitationSetupRequiredError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
