import logging
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import install_access_log_redaction
from app.core.observability import record_request
from app.db.init_db import initialize_database
from app.db.session import engine

settings = get_settings()
install_access_log_redaction()
request_logger = logging.getLogger("uvicorn.error.wbs.requests")


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
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type"],
    expose_headers=["Content-Disposition", "Retry-After", "X-Correlation-ID"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    correlation_id = str(uuid4())
    started_at = perf_counter()
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            request_size = int(content_length)
        except ValueError:
            request_size = -1
        if request_size < 0:
            response = JSONResponse(status_code=400, content={"detail": "Invalid Content-Length."})
        elif request_size > settings.max_request_body_bytes:
            response = JSONResponse(
                status_code=413,
                content={"detail": "Request body exceeds the configured limit."},
            )
        else:
            response = await call_next(request)
    else:
        response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if (
        request.url.path.startswith(f"{settings.api_v1_prefix}/auth")
        or "authorization" in request.headers
        or settings.auth_refresh_cookie_name in request.cookies
    ):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    if settings.app_env == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        )
    duration_seconds = perf_counter() - started_at
    route = request.scope.get("route")
    route_path = getattr(route, "path", "unmatched")
    record_request(request.method, route_path, response.status_code, duration_seconds)
    request_logger.info(
        "request_completed correlation_id=%s method=%s path=%s status=%s duration_ms=%s",
        correlation_id,
        request.method,
        request.url.path,
        response.status_code,
        round(duration_seconds * 1000),
    )
    return response


app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "docs": "/docs"}
