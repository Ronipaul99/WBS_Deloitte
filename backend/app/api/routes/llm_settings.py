"""Tenant administration; all outbound work is dispatched through the test outbox."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.routing import APIRoute
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.authorization import require_permission
from app.api.dependencies import TenantContext, require_tenant_member
from app.core.config import Settings, get_settings
from app.core.permissions import Permission
from app.db.session import get_db
from app.schemas.llm import (
    ConnectionCreate,
    ConnectionPublic,
    ConnectionUpdate,
    CredentialUpdate,
    ProfileCreate,
    ProfilePublic,
    ProfileState,
    ProfileUpdate,
    TestPublic,
    TestSubmit,
)
from app.services.agents.scoped_storage import StorageAccess
from app.services.llm.endpoint_policy import EndpointRegistry
from app.services.llm.errors import LlmSecurityError
from app.services.llm.management import AUTH, ModelManagement, operator_json
from app.services.llm.management_types import ManagementError
from app.services.llm.security_config import load_runtime_security


class PrivateManagementRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            try:
                response = await original(request)
                response.headers["Cache-Control"] = "no-store"
                return response
            except RequestValidationError:
                # Never return Pydantic's raw input, ctx or body containing a key.
                code, status = "llm_invalid_request", 422
            except ResponseValidationError:
                code, status = "llm_response_unavailable", 503
            except ManagementError as error:
                code, status = error.code, error.status
            except PermissionError:
                code, status = "llm_access_denied", 403
            except LlmSecurityError:
                code, status = "llm_security_unavailable", 503
            except IntegrityError:
                code, status = "llm_conflict", 409
            except SQLAlchemyError:
                code, status = "llm_storage_unavailable", 503
            except (ValueError, TypeError):
                code, status = "llm_invalid_request", 422
            raise HTTPException(
                status,
                detail={
                    "code": code,
                    "message": "AI model settings unavailable. Check configuration and retry.",
                },
                headers={"Cache-Control": "no-store"},
            ) from None

        return handle


router = APIRouter(
    prefix="/tenants/{tenant_id}/llm",
    tags=["AI model settings"],
    route_class=PrivateManagementRoute,
)
admin = Depends(require_permission(Permission.LLM_MANAGE))
use = Depends(require_permission(Permission.LLM_USE))


def get_management(
    context: TenantContext = Depends(require_tenant_member),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not settings.llm_management_enabled:
        raise ManagementError("llm_management_disabled")
    endpoints = EndpointRegistry.parse(settings.llm_egress_policy)
    keys = load_runtime_security(settings).keys if settings.llm_security_enabled else None
    return ModelManagement(
        async_sessionmaker(db.bind, expire_on_commit=False),
        StorageAccess(context.tenant.id, context.user.id),
        endpoints,
        keys,
        permits=operator_json(settings.llm_test_authorizations),
        tests_enabled=settings.llm_connection_tests_enabled,
    )


@router.get("/endpoints")
async def endpoints(context: TenantContext = admin, service=Depends(get_management)):
    async with service.sessions.begin() as session:
        await service.authorize(session)
    return [
        {
            "id": str(e.approval_id),
            "host": e.host,
            "port": e.port,
            "path_prefix": e.path_prefix,
            "auth_scheme": e.auth_scheme,
            "providers": [p for p, schemes in AUTH.items() if e.auth_scheme in schemes],
        }
        for e in service.endpoints.approved_endpoints()
    ]


@router.get("/connections", response_model=list[ConnectionPublic])
async def connections(context: TenantContext = admin, service=Depends(get_management)):
    return await service.connections()


@router.get("/connections/{identity}", response_model=ConnectionPublic)
async def connection(
    identity: UUID, context: TenantContext = admin, service=Depends(get_management)
):
    async with service.sessions.begin() as session:
        await service.authorize(session)
        return service.public_connection(await service.connection(session, identity))


@router.post("/connections", status_code=201, response_model=ConnectionPublic)
async def create_connection(
    payload: ConnectionCreate, context: TenantContext = admin, service=Depends(get_management)
):
    return await service.save_connection(payload)


@router.patch("/connections/{identity}", response_model=ConnectionPublic)
async def update_connection(
    identity: UUID,
    payload: ConnectionUpdate,
    context: TenantContext = admin,
    service=Depends(get_management),
):
    return await service.save_connection(payload, identity)


@router.post("/connections/{identity}/credentials/rotate", response_model=ConnectionPublic)
async def credentials(
    identity: UUID,
    payload: CredentialUpdate,
    context: TenantContext = admin,
    service=Depends(get_management),
):
    if payload.change.action not in {"replace", "rotate", "clear", "disable"}:
        raise ManagementError("llm_explicit_credential_action_required", 422)
    return await service.credential(identity, payload)


@router.post("/connections/{identity}/test", status_code=202, response_model=TestPublic)
async def submit_test(
    identity: UUID,
    payload: TestSubmit,
    context: TenantContext = admin,
    service=Depends(get_management),
):
    return await service.submit_test(identity, payload)


@router.get("/connections/{identity}/tests/{test_id}", response_model=TestPublic)
async def test_status(
    identity: UUID, test_id: UUID, context: TenantContext = admin, service=Depends(get_management)
):
    return await service.get_test(identity, test_id)


@router.get("/usable-profiles", response_model=list[ProfilePublic])
async def usable_profiles(context: TenantContext = use, service=Depends(get_management)):
    return await service.profiles(catalog=True)


@router.get("/profiles", response_model=list[ProfilePublic])
async def profiles(context: TenantContext = admin, service=Depends(get_management)):
    return await service.profiles()


@router.get("/profiles/{identity}", response_model=ProfilePublic)
async def profile(identity: UUID, context: TenantContext = admin, service=Depends(get_management)):
    async with service.sessions.begin() as session:
        await service.authorize(session)
        return await service.public_profile(session, await service.profile(session, identity))


@router.post("/profiles", status_code=201, response_model=ProfilePublic)
async def create_profile(
    payload: ProfileCreate, context: TenantContext = admin, service=Depends(get_management)
):
    return await service.save_profile(payload)


@router.patch("/profiles/{identity}", response_model=ProfilePublic)
async def update_profile(
    identity: UUID,
    payload: ProfileUpdate,
    context: TenantContext = admin,
    service=Depends(get_management),
):
    return await service.save_profile(payload, identity)


@router.post("/profiles/{identity}/state", response_model=ProfilePublic)
async def profile_state(
    identity: UUID,
    payload: ProfileState,
    context: TenantContext = admin,
    service=Depends(get_management),
):
    return await service.set_profile_state(identity, payload)
