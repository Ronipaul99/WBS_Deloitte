"""Transaction-scoped repository boundary; no global engine/settings imports."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission, assert_llm_permission, permissions_for_role
from app.models.domain import Tenant, TenantMembership, User


@dataclass(frozen=True)
class StorageAccess:
    """Trusted authenticated identity supplied by application code, never by an LLM."""

    tenant_id: UUID
    user_id: UUID

    def __post_init__(self):
        if any(
            not isinstance(value, UUID) or value.int == 0
            for value in (self.tenant_id, self.user_id)
        ):
            raise ValueError("storage access requires non-nil UUID identities")


class ScopedStorage:
    def __init__(self, session: AsyncSession, access: StorageAccess):
        self.session = session
        self.access = access

    async def authorize(self, permission: Permission, run_id: UUID | None = None):
        if not self.session.in_transaction():
            raise RuntimeError("scoped storage requires an explicit active transaction")
        if self.session.get_bind().dialect.name == "postgresql":
            # Rebind for every operation/transaction; no session-level GUC survives pooling.
            for key, value in (
                ("app.tenant_id", self.access.tenant_id),
                ("app.agent_workflow_run_id", run_id or ""),
                ("app.agent_user_id", self.access.user_id),
            ):
                await self.session.execute(
                    text("SELECT set_config(:key, :value, true)"), {"key": key, "value": str(value)}
                )
        role = await self.session.scalar(
            select(TenantMembership.role)
            .join(User, User.id == TenantMembership.user_id)
            .join(Tenant, Tenant.id == TenantMembership.tenant_id)
            .where(
                TenantMembership.tenant_id == self.access.tenant_id,
                TenantMembership.user_id == self.access.user_id,
                Tenant.is_active.is_(True),
                User.is_active.is_(True),
            )
        )
        if role is None:
            raise PermissionError("storage access denied")
        if permission in (Permission.LLM_USE, Permission.LLM_MANAGE, Permission.LLM_USAGE_AUDIT):
            assert_llm_permission(role, permission)
        elif permission not in permissions_for_role(role):
            raise PermissionError("storage access denied")

    def check_tenant(self, record):
        if record.tenant_id != self.access.tenant_id:
            raise PermissionError("record is outside authorized tenant")
