import logging
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from app.models.domain import MembershipRole

logger = logging.getLogger(__name__)


class Permission(StrEnum):
    PROJECT_READ = "project:read"
    PROJECT_CREATE = "project:create"
    PROJECT_UPDATE = "project:update"
    PROJECT_ARCHIVE = "project:archive"
    DOCUMENT_READ = "document:read"
    DOCUMENT_UPLOAD = "document:upload"
    DOCUMENT_PROCESS = "document:process"
    SUMMARY_READ = "summary:read"
    SUMMARY_UPDATE = "summary:update"
    SUMMARY_APPROVE = "summary:approve"
    TEMPLATE_READ = "template:read"
    TEMPLATE_MANAGE = "template:manage"
    WBS_READ = "wbs:read"
    WBS_GENERATE = "wbs:generate"
    WBS_UPDATE = "wbs:update"
    VALIDATION_READ = "validation:read"
    VALIDATION_RUN = "validation:run"
    EXPORT_READ = "export:read"
    EXPORT_CREATE = "export:create"
    JOB_READ = "job:read"
    JOB_MANAGE = "job:manage"
    MEMBER_READ = "member:read"
    MEMBER_INVITE = "member:invite"
    MEMBER_UPDATE = "member:update"
    MEMBER_REMOVE = "member:remove"
    AUDIT_READ = "audit:read"
    LLM_MANAGE = "llm:manage"
    LLM_USE = "llm:use"
    LLM_USAGE_AUDIT = "llm:usage_audit"


VIEWER_PERMISSIONS: Final = frozenset(
    {
        Permission.PROJECT_READ,
        Permission.DOCUMENT_READ,
        Permission.SUMMARY_READ,
        Permission.TEMPLATE_READ,
        Permission.WBS_READ,
        Permission.VALIDATION_READ,
        Permission.EXPORT_READ,
        Permission.JOB_READ,
    }
)

EDITOR_PERMISSIONS: Final = VIEWER_PERMISSIONS | frozenset(
    {
        Permission.PROJECT_CREATE,
        Permission.PROJECT_UPDATE,
        Permission.DOCUMENT_UPLOAD,
        Permission.DOCUMENT_PROCESS,
        Permission.SUMMARY_UPDATE,
        Permission.LLM_USE,
        Permission.SUMMARY_APPROVE,
        Permission.TEMPLATE_MANAGE,
        Permission.WBS_GENERATE,
        Permission.WBS_UPDATE,
        Permission.VALIDATION_RUN,
        Permission.EXPORT_CREATE,
        Permission.JOB_MANAGE,
    }
)

ADMIN_PERMISSIONS: Final = EDITOR_PERMISSIONS | frozenset(
    {
        Permission.PROJECT_ARCHIVE,
        Permission.MEMBER_READ,
        Permission.MEMBER_INVITE,
        Permission.MEMBER_UPDATE,
        Permission.MEMBER_REMOVE,
        Permission.AUDIT_READ,
        Permission.LLM_MANAGE,
        Permission.LLM_USAGE_AUDIT,
    }
)

ROLE_PERMISSIONS: Final[Mapping[MembershipRole, frozenset[Permission]]] = MappingProxyType(
    {
        MembershipRole.VIEWER: VIEWER_PERMISSIONS,
        MembershipRole.EDITOR: EDITOR_PERMISSIONS,
        MembershipRole.ADMIN: ADMIN_PERMISSIONS,
    }
)

NO_PERMISSIONS: Final = frozenset()


def resolve_membership_role(value: str) -> MembershipRole | None:
    try:
        return MembershipRole(value)
    except ValueError:
        logger.warning("Authorization denied because a membership has an unknown role")
        return None


def permissions_for_role(value: str | MembershipRole) -> frozenset[Permission]:
    role = resolve_membership_role(str(value))
    return ROLE_PERMISSIONS.get(role, NO_PERMISSIONS) if role is not None else NO_PERMISSIONS


def assert_llm_permission(role: str | MembershipRole, permission: Permission) -> None:
    """Server-side repository guard; authentication supplies membership identity."""
    if permission not in {Permission.LLM_MANAGE, Permission.LLM_USE, Permission.LLM_USAGE_AUDIT}:
        raise ValueError("an LLM permission is required")
    granted = permissions_for_role(role)
    if permission not in granted or (
        permission == Permission.LLM_USE and Permission.SUMMARY_UPDATE not in granted
    ):
        raise PermissionError("model access denied")
