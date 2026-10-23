from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authorization import TENANT_AUTH_RESPONSES, require_permission
from app.api.dependencies import TenantContext
from app.api.routes.helpers import get_tenant_project
from app.core.permissions import Permission
from app.db.session import get_db
from app.models.domain import Project, ProjectStatus
from app.schemas.domain import ProjectCreate, ProjectResponse, ProjectUpdate

router = APIRouter(
    prefix="/tenants/{tenant_id}/projects",
    tags=["projects"],
    responses=TENANT_AUTH_RESPONSES,
)


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    context: TenantContext = Depends(require_permission(Permission.PROJECT_CREATE)),
    db: AsyncSession = Depends(get_db),
) -> Project:
    project = Project(
        tenant_id=context.tenant.id,
        created_by=context.user.id,
        name=payload.name.strip(),
        description=payload.description,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    include_archived: bool = False,
    context: TenantContext = Depends(require_permission(Permission.PROJECT_READ)),
    db: AsyncSession = Depends(get_db),
) -> list[Project]:
    query = select(Project).where(Project.tenant_id == context.tenant.id)
    if not include_archived:
        query = query.where(Project.status == ProjectStatus.ACTIVE)
    result = await db.scalars(query.order_by(Project.created_at.desc()))
    return list(result)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.PROJECT_READ)),
    db: AsyncSession = Depends(get_db),
) -> Project:
    return await get_tenant_project(db, context.tenant.id, project_id)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    context: TenantContext = Depends(require_permission(Permission.PROJECT_UPDATE)),
    db: AsyncSession = Depends(get_db),
) -> Project:
    project = await get_tenant_project(db, context.tenant.id, project_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value.strip() if isinstance(value, str) else value)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_project(
    project_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.PROJECT_ARCHIVE)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    project = await get_tenant_project(db, context.tenant.id, project_id)
    project.status = ProjectStatus.ARCHIVED
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
