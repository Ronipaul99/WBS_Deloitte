from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import TenantContext, require_tenant_member
from app.core.config import Settings, get_settings
from app.core.permissions import Permission
from app.db.session import get_db
from app.models.domain import MembershipRole
from app.services.auth import add_auth_event, request_fingerprints

TenantAuthorizationDependency = Callable[..., Awaitable[TenantContext]]

TENANT_AUTH_RESPONSES = {
    401: {"description": "A valid bearer access token is required."},
    403: {"description": "The user is not a member or lacks the required permission."},
    404: {"description": "The tenant or tenant-owned resource was not found."},
}


def require_permission(permission: Permission) -> TenantAuthorizationDependency:
    async def permission_dependency(
        request: Request,
        context: TenantContext = Depends(require_tenant_member),
        db: AsyncSession = Depends(get_db),
        settings: Settings = Depends(get_settings),
    ) -> TenantContext:
        if permission not in context.permissions:
            ip_hash, user_agent_hash = request_fingerprints(request, settings)
            route = request.scope.get("route")
            add_auth_event(
                db,
                event_type="authorization_denied",
                success=False,
                user_id=context.user.id,
                subject_hash=None,
                ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
                details={
                    "tenant_id": str(context.tenant.id),
                    "permission": permission.value,
                    "route": getattr(route, "path", "unmatched"),
                },
            )
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this operation.",
            )
        return context

    permission_dependency.__name__ = f"require_{permission.value.replace(':', '_')}"
    return permission_dependency


def require_role(*roles: MembershipRole) -> TenantAuthorizationDependency:
    allowed_roles = frozenset(roles)

    async def role_dependency(
        request: Request,
        context: TenantContext = Depends(require_tenant_member),
        db: AsyncSession = Depends(get_db),
        settings: Settings = Depends(get_settings),
    ) -> TenantContext:
        if context.role not in allowed_roles:
            ip_hash, user_agent_hash = request_fingerprints(request, settings)
            route = request.scope.get("route")
            add_auth_event(
                db,
                event_type="authorization_denied",
                success=False,
                user_id=context.user.id,
                subject_hash=None,
                ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
                details={
                    "tenant_id": str(context.tenant.id),
                    "required_roles": ",".join(sorted(role.value for role in allowed_roles)),
                    "route": getattr(route, "path", "unmatched"),
                },
            )
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this operation.",
            )
        return context

    role_dependency.__name__ = "require_role_" + "_".join(sorted(role.value for role in roles))
    return role_dependency
