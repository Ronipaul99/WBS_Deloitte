from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.domain import HealthResponse

router = APIRouter(prefix="/health", tags=["system"])


@router.get("/live", response_model=HealthResponse)
async def liveness(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(status="ok", service=settings.app_name, environment=settings.app_env)


@router.get("/ready", response_model=HealthResponse)
async def readiness(
    db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> HealthResponse:
    await db.execute(text("SELECT 1"))
    return HealthResponse(status="ready", service=settings.app_name, environment=settings.app_env)
