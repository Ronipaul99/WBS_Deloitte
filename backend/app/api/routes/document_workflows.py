from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.api.authorization import TENANT_AUTH_RESPONSES, require_permission
from app.api.dependencies import TenantContext
from app.api.routes.documents import PROJECT_CONTENT_TYPES, PROJECT_EXTENSIONS
from app.api.routes.helpers import get_tenant_project, get_tenant_template
from app.core.config import Settings, get_settings
from app.core.permissions import Permission
from app.core.upload_errors import UploadErrorCode, upload_http_error
from app.db.session import get_db, set_local_tenant_context
from app.models.document_workflows import DocumentUploadAttempt, DocumentWorkflow
from app.models.domain import WbsTemplate
from app.schemas.document_workflows import (
    ForkWorkflow,
    ResolveDocument,
    ResolveResponse,
    UploadWorkflowResponse,
    WorkflowState,
)
from app.services.document_content import conflict, resolve_content, upload_or_reuse
from app.services.document_workflow_resume import load_workflow, resume_state
from app.services.storage import (
    ObjectStorageUnavailableError,
    UploadObjectStorage,
    get_upload_storage,
)


class PrivateWorkflowRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def sanitized(request: Request):
            try:
                return await handler(request)
            except SQLAlchemyError:
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": {
                            "code": "WORKFLOW_STORAGE_UNAVAILABLE",
                            "message": "Saved work is temporarily unavailable. Try again shortly.",
                        }
                    },
                )

        return sanitized


router = APIRouter(
    prefix="/tenants/{tenant_id}/document-workflows",
    tags=["document-workflows"],
    responses=TENANT_AUTH_RESPONSES,
    route_class=PrivateWorkflowRoute,
)


def enabled_settings(settings: Settings = Depends(get_settings)) -> Settings:
    if not settings.document_workflow_resume_enabled:
        raise HTTPException(404, detail="Document workflow recovery is not enabled.")
    return settings


@router.get("/capabilities")
async def capabilities(
    _: TenantContext = Depends(require_permission(Permission.DOCUMENT_READ)),
    settings: Settings = Depends(get_settings),
) -> dict:
    return {
        "resume_enabled": settings.document_workflow_resume_enabled,
        "reuse_enabled": settings.document_upload_reuse_enabled,
        "max_upload_bytes": settings.max_upload_bytes,
    }


@router.post("/resolve", response_model=ResolveResponse)
async def resolve(
    payload: ResolveDocument,
    context: TenantContext = Depends(require_permission(Permission.DOCUMENT_READ)),
    settings: Settings = Depends(enabled_settings),
    db: AsyncSession = Depends(get_db),
) -> ResolveResponse:
    await get_tenant_project(db, context.tenant.id, payload.selected_project_id)
    if payload.size_bytes > settings.max_upload_bytes:
        raise upload_http_error(UploadErrorCode.DOCUMENT_TOO_LARGE)
    return await resolve_content(
        db,
        tenant_id=context.tenant.id,
        sha256=payload.sha256,
        size_bytes=payload.size_bytes,
        selected_project_id=payload.selected_project_id,
        permissions=context.permissions,
    )


@router.post("/uploads", response_model=UploadWorkflowResponse)
async def upload(
    request: Request,
    response: Response,
    context: TenantContext = Depends(require_permission(Permission.DOCUMENT_UPLOAD)),
    settings: Settings = Depends(enabled_settings),
    db: AsyncSession = Depends(get_db),
    storage: UploadObjectStorage = Depends(get_upload_storage),
) -> UploadWorkflowResponse:
    from pathlib import Path

    if not settings.document_upload_reuse_enabled:
        raise HTTPException(409, detail="Content reuse enforcement is not enabled.")
    form = await request.form()
    file = form.get("file")
    if not isinstance(file, UploadFile):
        raise HTTPException(422, detail="A document file is required.")
    try:
        try:
            project_id = UUID(str(form.get("project_id")))
        except ValueError:
            raise HTTPException(422, detail="A project ID is required.") from None
        project = await get_tenant_project(db, context.tenant.id, project_id)
        if project.status != "ACTIVE":
            raise HTTPException(409, detail="The selected project is archived.")
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in PROJECT_EXTENSIONS:
            raise upload_http_error(UploadErrorCode.UNSUPPORTED_DOCUMENT_FORMAT)
        content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
        if content_type not in PROJECT_CONTENT_TYPES[suffix]:
            raise upload_http_error(UploadErrorCode.DOCUMENT_TYPE_MISMATCH)
        disposition, _, workflow_id, handle = await upload_or_reuse(
            db,
            context=context,
            project_id=project_id,
            file=file,
            suffix=suffix,
            content_type="application/pdf" if suffix == ".pdf" else content_type,
            storage=storage,
            settings=settings,
            client_sha256=form.get("sha256"),
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        response.status_code = {"CREATED": 201, "REUSED": 200, "UPLOAD_PENDING": 202}[disposition]
        if disposition == "UPLOAD_PENDING":
            response.headers["Retry-After"] = "2"
        return UploadWorkflowResponse(
            disposition=disposition,
            upload_handle=handle,
            workflow=await resume_state(db, context.tenant.id, workflow_id, context.permissions)
            if workflow_id
            else None,
        )
    except ObjectStorageUnavailableError:
        raise upload_http_error(UploadErrorCode.OBJECT_STORAGE_UNAVAILABLE) from None
    finally:
        await file.close()


@router.get("/uploads/{handle}")
async def upload_status(
    handle: UUID,
    context: TenantContext = Depends(require_permission(Permission.DOCUMENT_READ)),
    _: Settings = Depends(enabled_settings),
    db: AsyncSession = Depends(get_db),
):
    await set_local_tenant_context(db, context.tenant.id)
    attempt = await db.scalar(
        select(DocumentUploadAttempt).where(
            DocumentUploadAttempt.id == handle,
            DocumentUploadAttempt.tenant_id == context.tenant.id,
        )
    )
    if attempt is None:
        raise HTTPException(404, detail="Upload not found.")
    if attempt.state == "COMMITTED":
        workflow = await db.scalar(
            select(DocumentWorkflow).where(
                DocumentWorkflow.tenant_id == context.tenant.id,
                DocumentWorkflow.document_id == attempt.document_id,
                DocumentWorkflow.is_base.is_(True),
            )
        )
        if workflow:
            state = await resume_state(db, context.tenant.id, workflow.id, context.permissions)
            return {"disposition": "REUSED", "workflow": state.model_dump(mode="json")}
    if attempt.state in {"ABANDONED", "CLEANED"}:
        raise conflict(
            "UPLOAD_INTERRUPTED", "The upload was interrupted. Check existing work again."
        )
    return JSONResponse(
        status_code=202,
        headers={"Retry-After": "2"},
        content={
            "disposition": "UPLOAD_PENDING",
            "upload_handle": str(handle),
        },
    )


@router.get("/projects/{project_id}", response_model=list[WorkflowState])
async def project_workflows(
    project_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.DOCUMENT_READ)),
    _: Settings = Depends(enabled_settings),
    db: AsyncSession = Depends(get_db),
):
    await get_tenant_project(db, context.tenant.id, project_id)
    await set_local_tenant_context(db, context.tenant.id)
    workflows = await db.scalars(
        select(DocumentWorkflow)
        .where(
            DocumentWorkflow.tenant_id == context.tenant.id,
            DocumentWorkflow.project_id == project_id,
        )
        .order_by(DocumentWorkflow.updated_at.desc(), DocumentWorkflow.id)
    )
    states = []
    for workflow in workflows:
        try:
            states.append(
                await resume_state(db, context.tenant.id, workflow.id, context.permissions)
            )
        except HTTPException as exc:
            if exc.status_code not in {404, 410}:
                raise
    return states


@router.get("/documents/{document_id}", response_model=list[WorkflowState])
async def document_workflows(
    document_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.DOCUMENT_READ)),
    _: Settings = Depends(enabled_settings),
    db: AsyncSession = Depends(get_db),
):
    from app.services.document_workflow_resume import scoped_document

    await scoped_document(db, context.tenant.id, document_id)
    ids = await db.scalars(
        select(DocumentWorkflow.id)
        .where(
            DocumentWorkflow.tenant_id == context.tenant.id,
            DocumentWorkflow.document_id == document_id,
        )
        .order_by(DocumentWorkflow.created_at.desc(), DocumentWorkflow.id)
    )
    return [await resume_state(db, context.tenant.id, value, context.permissions) for value in ids]


@router.post("/{workflow_id}/fork", response_model=WorkflowState, status_code=201)
async def fork(
    workflow_id: UUID,
    payload: ForkWorkflow,
    context: TenantContext = Depends(require_permission(Permission.WBS_GENERATE)),
    _: Settings = Depends(enabled_settings),
    db: AsyncSession = Depends(get_db),
):
    original, document = await load_workflow(db, context.tenant.id, workflow_id, lock=True)
    if payload.expected_revision and original.checkpoint_revision != payload.expected_revision:
        raise conflict("WORKFLOW_CHANGED", "The workflow changed. Refresh before continuing.")
    template: WbsTemplate | None = None
    if payload.template_id:
        template = await get_tenant_template(db, context.tenant.id, payload.template_id)
        if not template.is_active:
            raise HTTPException(409, detail="The selected template is inactive.")
    workflow = DocumentWorkflow(
        tenant_id=context.tenant.id,
        project_id=document.project_id,
        document_id=document.id,
        processing_run_id=document.current_processing_run_id,
        template_id=payload.template_id,
        template_identity={"id": str(template.id)} if template else {},
    )
    db.add(workflow)
    await db.commit()
    return await resume_state(db, context.tenant.id, workflow.id, context.permissions)


@router.patch("/{workflow_id}/template", response_model=WorkflowState)
async def select_template(
    workflow_id: UUID,
    payload: ForkWorkflow,
    context: TenantContext = Depends(require_permission(Permission.WBS_GENERATE)),
    _: Settings = Depends(enabled_settings),
    db: AsyncSession = Depends(get_db),
):
    workflow, _ = await load_workflow(db, context.tenant.id, workflow_id, lock=True)
    if workflow.generation_job_id:
        raise conflict(
            "GENERATION_ALREADY_STARTED", "Create a new workflow to change its template."
        )
    if payload.expected_revision and payload.expected_revision != workflow.checkpoint_revision:
        raise conflict("WORKFLOW_CHANGED", "The workflow changed. Refresh before continuing.")
    if payload.template_id:
        template = await get_tenant_template(db, context.tenant.id, payload.template_id)
        if not template.is_active:
            raise HTTPException(409, detail="The selected template is inactive.")
    workflow.template_id = payload.template_id
    workflow.checkpoint_revision += 1
    await db.commit()
    return await resume_state(db, context.tenant.id, workflow.id, context.permissions)


@router.get("/{workflow_id}", response_model=WorkflowState)
async def get_workflow(
    workflow_id: UUID,
    response: Response,
    context: TenantContext = Depends(require_permission(Permission.DOCUMENT_READ)),
    _: Settings = Depends(enabled_settings),
    db: AsyncSession = Depends(get_db),
):
    state = await resume_state(db, context.tenant.id, workflow_id, context.permissions)
    response.headers["ETag"] = f'"{state.checkpoint_revision}"'
    response.headers["Cache-Control"] = "no-store"
    return state
