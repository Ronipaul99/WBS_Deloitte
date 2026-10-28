"""Test-only ASGI harness. Never loaded by the application or production worker.

A loopback HTTP adapter substitutes only the external network boundary. All
application routes, submission, exact lookup, import and review code are real.
This simulates delivery/reconciler turns; it is NOT a Celery deployment test.
"""

import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

ROOT = Path(os.environ["SUMMARY_TEST_ROOT"]).resolve()
ALLOWED = Path(__file__).resolve().parents[2] / ".data" / "external-summary-step06"
if not ROOT.is_relative_to(ALLOWED.resolve()) or not ROOT.name.startswith("run-"):
    raise RuntimeError("Refusing non-isolated summary harness root")
API_PORT = int(os.environ["SUMMARY_TEST_API_PORT"])
FAKE_PORT = int(os.environ["SUMMARY_TEST_FAKE_PORT"])
UI_PORT = int(os.environ["SUMMARY_TEST_UI_PORT"])
# Construct database/storage destinations; never consume a caller DATABASE_URL.
os.environ.update(
    APP_ENV="test",
    AUTH_MODE="local",
    DATABASE_URL=f"sqlite+aiosqlite:///{(ROOT / 'db.sqlite').as_posix()}",
    DIRECT_DATABASE_URL="",
    DATABASE_MIGRATION_ROLE_NAME="",
    DATABASE_USE_NULL_POOL="false",
    UPLOAD_ROOT=str(ROOT / "uploads"),
    STORAGE_BACKEND="local",
    AUTO_CREATE_TABLES="true",
    TASKS_EAGER="false",
    DOCUMENT_INGESTION_ENABLED="false",
    DOCUMENT_INGESTION_LOCAL_DEVELOPMENT="false",
    DOCUMENT_WORKFLOW_RESUME_ENABLED="true",
    DOCUMENT_UPLOAD_REUSE_ENABLED="true",
    EMBEDDING_MODEL_REVISION="a" * 40,
    EXTERNAL_SUMMARY_ENABLED="true",
    EXTERNAL_SUMMARY_API_KEY=os.environ["SUMMARY_TEST_UPSTREAM_KEY"],
    EXTERNAL_SUMMARY_BASE_URL="https://caring-doormat-pounce.ngrok-free.dev",
    PUBLIC_UI_URL=f"http://127.0.0.1:{UI_PORT}",
    CORS_ORIGINS=f"http://127.0.0.1:{UI_PORT}",
)
from app.core import config  # noqa: E402


@lru_cache
def settings():
    return config.Settings(_env_file=None)


config.get_settings = settings
from app.db import session as db_session  # noqa: E402
from app.db.session import SessionLocal, ensure_tenant_transaction  # noqa: E402

_original_scope = db_session.set_local_tenant_context


async def strict_scope(db, tenant):
    if not db.in_transaction():
        raise RuntimeError("Tenant context requires an active database transaction")
    await _original_scope(db, tenant)


db_session.set_local_tenant_context = strict_scope
from app.main import app  # noqa: E402
from app.models.domain import Document, DocumentChunk, DocumentSummary, Job  # noqa: E402
from app.models.external_summary import SummaryApiRequest, SummaryResultImport  # noqa: E402
from app.services import external_summary_submission as submission  # noqa: E402
from app.services.external_summary_import import reconcile_imports  # noqa: E402
from app.services.external_summary_tracking import reconcile_tracking  # noqa: E402
from app.services.external_summary_transport import ORIGIN, PATH, submit_document  # noqa: E402
from tests.test_document_deduplication_api import ready_ingestion  # noqa: E402
from tests.test_external_summary_import import TEXT, result_payload  # noqa: E402

TENANT = settings().dev_tenant_id
queue = asyncio.Queue()
active = True
errors = []


class LoopbackOnly(httpx.AsyncBaseTransport):
    def __init__(self):
        self.inner = httpx.AsyncHTTPTransport(trust_env=False)

    async def handle_async_request(self, request):
        if str(request.url) != ORIGIN + PATH or request.method != "POST":
            raise RuntimeError("Unexpected test outbound operation")
        forwarded = httpx.Request(
            "POST",
            f"http://127.0.0.1:{FAKE_PORT}/summary",
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
            content=await request.aread(),
            extensions=request.extensions,
        )
        return await self.inner.handle_async_request(forwarded)

    async def aclose(self):
        await self.inner.aclose()


async def send(document_id, policy):
    return await submit_document(document_id, policy, transport=LoopbackOnly())


async def turn():
    while not queue.empty():
        kind, args = queue.get_nowait()
        if kind == "submit":
            await submission.process_submission(UUID(args[0]), UUID(args[1]), submit=send)
        else:
            from app.services.document_lifecycle import process_document_deletion

            await process_document_deletion(UUID(args[0]), UUID(args[1]))
    await reconcile_tracking()
    await reconcile_imports()


async def pump():
    while True:
        if active:
            try:
                await turn()
            except Exception as error:
                errors.append(type(error).__name__)  # metadata only
        await asyncio.sleep(0.2)


original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def lifespan(instance):
    from app.services.dispatcher import dispatch_app

    loop = asyncio.get_running_loop()
    original_send = dispatch_app.send_task

    def deliver(name, args, **kwargs):
        if name not in {submission.TASK, "wbs.cleanup_document_deletion"} or len(args) != 2:
            raise RuntimeError("Unsupported test delivery")
        loop.call_soon_threadsafe(
            queue.put_nowait, ("submit" if name == submission.TASK else "delete", tuple(args))
        )

    dispatch_app.send_task = deliver
    async with original_lifespan(instance):
        task = asyncio.create_task(pump())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            dispatch_app.send_task = original_send


app.router.lifespan_context = lifespan


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: UUID | None = None
    status: str = "RUNNING"
    progress: int = 25
    payload: str = "valid"
    mode: str = "normal"
    active: bool = True


def authorize(token):
    if token != os.environ["SUMMARY_TEST_CONTROL_TOKEN"]:
        raise HTTPException(403)


async def owned_document(db, identity):
    await ensure_tenant_transaction(db, TENANT)
    document = await db.scalar(
        select(Document).where(Document.id == identity, Document.tenant_id == TENANT)
    )
    if document is None:
        raise HTTPException(404)
    return document


@app.post("/__summary_test/{operation}", include_in_schema=False)
async def control(operation: str, body: Control, x_test_token: str = Header(default="")):
    global active
    authorize(x_test_token)
    if operation == "pump":
        active = body.active
        if active:
            await submission.reconcile_submissions()
        return {"active": active}
    if operation == "mode":
        (ROOT / "mode.txt").write_text(body.mode, encoding="utf-8")
        return {"configured": True}
    if operation == "ready":
        async with SessionLocal() as db:
            await owned_document(db, body.document_id)
        await ready_ingestion(str(body.document_id))
        async with SessionLocal() as db:
            await owned_document(db, body.document_id)
            chunk = await db.scalar(
                select(DocumentChunk).where(DocumentChunk.document_id == body.document_id)
            )
            chunk.content, chunk.content_sha256 = TEXT, hashlib.sha256(TEXT.encode()).hexdigest()
            chunk.page_number, chunk.source_metadata = 1, {"page_numbers": [1]}
            await db.commit()
        return {"ready": True, "synthetic_ingestion_fixture": True}
    async with SessionLocal() as db:
        document = await owned_document(db, body.document_id)
        record = await db.scalar(
            select(SummaryApiRequest).where(
                SummaryApiRequest.document_id == document.id, SummaryApiRequest.tenant_id == TENANT
            )
        )
        if record is None:
            return {"request_id": None, "errors": errors}
        job = await db.get(Job, record.external_job_id) if record.external_job_id else None
        if operation == "step":
            if job is None:
                raise HTTPException(409)
            job.status, job.progress, job.current_step = (
                body.status,
                body.progress,
                f"SUMMARY:TEST_{body.progress}",
            )
            if body.payload == "valid":
                chunk = await db.scalar(
                    select(DocumentChunk).where(DocumentChunk.document_id == document.id)
                )
                job.result_payload = result_payload(
                    {"project_id": str(document.project_id), "document_id": str(document.id)},
                    record.processing_run_id,
                    chunk.id,
                )
            else:
                job.result_payload = {}
            await db.commit()
            return {"updated": True}
        if operation == "newer":
            db.add(
                Job(
                    tenant_id=TENANT,
                    project_id=document.project_id,
                    created_by=settings().dev_user_id,
                    job_type="DOCUMENT_SUMMERIZATION",
                    status="COMPLETED",
                    progress=100,
                    current_step="UNRELATED",
                    request_payload={"document_id": str(document.id)},
                    result_payload={"unrelated": True},
                )
            )
            await db.commit()
            return {"created": True}
        if operation == "invalidate":
            document.current_processing_run_id = None
            await db.commit()
            return {"invalidated": True}
        if operation == "due":
            row = await db.get(SummaryResultImport, record.id)
            if row and row.state == "WAITING":
                row.available_at = datetime.now(UTC)
                await db.commit()
            return {"due": True}
        if operation != "inspect":
            raise HTTPException(404)
        row = await db.get(SummaryResultImport, record.id)
        summary = await db.scalar(
            select(DocumentSummary).where(DocumentSummary.document_id == document.id)
        )
        events = (
            [json.loads(line) for line in (ROOT / "fake-events.jsonl").read_text().splitlines()]
            if (ROOT / "fake-events.jsonl").exists()
            else []
        )
        kinds = list(
            await db.scalars(
                select(Job.job_type).where(
                    Job.request_payload["document_id"].as_string() == str(document.id)
                )
            )
        )
        return {
            "request_id": str(record.id),
            "job_id": str(record.external_job_id) if record.external_job_id else None,
            "submission_state": record.state,
            "job_status": job.status if job else None,
            "import_state": row.state if row else None,
            "summary_id": str(summary.id) if summary else None,
            "revision": summary.revision if summary else None,
            "approved": summary.is_approved if summary else False,
            "upstream_calls": sum(e["document_id"] == str(document.id) for e in events),
            "legacy_jobs": kinds.count("DOCUMENT_SUMMARY"),
            "errors": errors,
            "result_digest": hashlib.sha256(
                json.dumps(job.result_payload, sort_keys=True).encode()
            ).hexdigest()
            if job
            else None,
        }


fake = FastAPI()


@fake.get("/")
def fake_health():
    return {"test_only": True}


@fake.post("/summary")
async def fake_summary(body: dict, x_api_key: str = Header(default="")):
    if x_api_key != os.environ["SUMMARY_TEST_UPSTREAM_KEY"] or set(body) != {"document_id"}:
        raise HTTPException(403)
    identity = UUID(body["document_id"])
    async with SessionLocal() as db:
        document = await owned_document(db, identity)
        job = Job(
            tenant_id=TENANT,
            project_id=document.project_id,
            created_by=settings().dev_user_id,
            job_type="DOCUMENT_SUMMERIZATION",
            status="RUNNING",
            progress=0,
            current_step="SUMMARY:QUEUED",
            request_payload={"document_id": str(identity)},
            result_payload={},
        )
        db.add(job)
        await db.commit()
        stamp = datetime.now(UTC).isoformat()
        with (ROOT / "fake-events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"document_id": str(identity), "job_id": str(job.id)}) + "\n")
        mode = (ROOT / "mode.txt").read_text() if (ROOT / "mode.txt").exists() else "normal"
        if mode == "ambiguous":
            raise HTTPException(503, detail="Synthetic acknowledgement lost after job creation")
        return {
            "job_id": str(job.id),
            "document_id": str(identity),
            "job_type": "DOCUMENT_SUMMERIZATION",
            "status": "RUNNING",
            "progress": 0,
            "current_step": "SUMMARY:QUEUED",
            "attempt_count": 0,
            "error_code": None,
            "error_message": None,
            "created_at": stamp,
            "updated_at": stamp,
            "result_url": f"/api/v2.1/project-summary/jobs/{job.id}/result",
        }
