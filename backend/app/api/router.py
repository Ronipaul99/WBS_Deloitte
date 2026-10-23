from fastapi import APIRouter

from app.api.routes import (
    auth,
    documents,
    exports,
    generations,
    health,
    identity,
    jobs,
    members,
    projects,
    sso,
    summaries,
    templates,
    validations,
    wbs,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(sso.router)
api_router.include_router(identity.router)
api_router.include_router(members.router)
api_router.include_router(projects.router)
api_router.include_router(documents.router)
api_router.include_router(summaries.router)
api_router.include_router(templates.router)
api_router.include_router(jobs.router)
api_router.include_router(generations.router)
api_router.include_router(wbs.router)
api_router.include_router(validations.router)
api_router.include_router(exports.router)
