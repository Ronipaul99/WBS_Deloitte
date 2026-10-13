from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.db.init_db import initialize_database
from app.db.session import engine

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.upload_root.mkdir(parents=True, exist_ok=True)
    await initialize_database()
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Tenant-aware API and asynchronous workflow foundation for WBS generation.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "docs": "/docs"}
