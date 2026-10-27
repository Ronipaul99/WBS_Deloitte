"""Existing-worker composition and bounded inline test-outbox reconciliation."""

import asyncio
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.domain import Job
from app.services.agents.scoped_storage import StorageAccess
from app.services.agents.storage import aware
from app.services.llm.credential_service import CredentialService
from app.services.llm.management import ModelManagement, operator_json
from app.services.llm.management_types import ManagementError
from app.services.llm.registry import create_provider
from app.services.llm.secure_transport import SecureJsonTransport
from app.services.llm.security_config import load_runtime_security
from app.services.llm.test_execution import TestExecution

TASK = "wbs.test_agent_connection"


async def with_worker_sessions(settings, operation):
    """One task event loop owns its connections; never reuse an asyncpg pool across runs."""
    if not settings.llm_management_enabled or not settings.llm_connection_tests_enabled:
        return
    engine = create_async_engine(settings.sqlalchemy_database_url, poolclass=NullPool)
    try:
        return await operation(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


class TestAuthorizer:
    def __init__(self, service, execution, fence):
        self.service, self.execution, self.fence = service, execution, fence

    async def prepare(self, connection_id, pinned, purpose):
        await self.execution.check(self.fence)
        return await self.service.prepare(connection_id, pinned, purpose)

    async def verify(self, receipt, pinned):
        await self.execution.check(self.fence)
        await self.service.verify(receipt, pinned)


async def management_for_job(sessions, settings, identity):
    if not settings.llm_management_enabled or not settings.llm_connection_tests_enabled:
        raise ManagementError("llm_tests_disabled")
    security = load_runtime_security(settings)
    async with sessions.begin() as session:
        job = await session.scalar(
            select(Job).where(Job.id == identity, Job.job_type == "LLM_CONNECTION_TEST")
        )
        if job is None or job.request_payload != {"llm_test_id": str(identity)}:
            raise ManagementError("llm_not_found", 404)
        access = StorageAccess(job.tenant_id, job.created_by)
    return ModelManagement(
        sessions,
        access,
        security.endpoints,
        security.keys,
        permits=operator_json(settings.llm_test_authorizations),
        tests_enabled=True,
    )


async def run_test(sessions, settings, identity):
    management = await management_for_job(sessions, settings, identity)
    execution = TestExecution(management, identity)

    def factory(config, budget, store, fence):
        credentials = CredentialService(
            sessions, management.access, management.keys, management.endpoints
        )
        transport = SecureJsonTransport(
            management.endpoints, TestAuthorizer(credentials, store, fence)
        )
        return create_provider(
            transport,
            config.profile,
            management.endpoints.pin(config.endpoint),
            budget,
            options=config.settings.options,
        )

    await execution.execute(
        factory,
        worker_identity=settings.llm_worker_identity,
        reviewed_limits=operator_json(settings.llm_test_reviewed_limits),
    )


async def publish_test(execution, broker):
    m = execution.management
    async with m.sessions.begin() as session:
        row, _, ledger = await execution.row(session, pins=False)
        if row.state in {"succeeded", "failed", "unavailable"}:
            return
        if ledger.deadline <= m.now():
            await execution.terminal(session, row, "unavailable", "llm_test_expired")
            return
        if row.state == "running":
            if row.lease_expires_at and aware(row.lease_expires_at) > m.now():
                return
            if ledger.calls:
                await execution.terminal(session, row, "failed", "llm_test_ambiguous_attempt")
                return
            row.state, row.fence = "queued", row.fence + 1
            row.delivery_state = "retry"
        if row.delivery_state == "published":
            if aware(row.available_at) > m.now():
                return
            row.delivery_state = "retry"
        if (
            row.delivery_state == "publishing"
            and row.delivery_lease_at
            and aware(row.delivery_lease_at) > m.now()
        ) or aware(row.available_at) > m.now():
            return
        if row.delivery_attempts >= 5:
            row.delivery_state = "dead"
            await execution.terminal(session, row, "failed", "llm_test_delivery_exhausted")
            return
        row.delivery_attempts += 1
        row.delivery_fence += 1
        token = row.delivery_fence
        row.delivery_state = "publishing"
        row.delivery_lease_at = m.now() + timedelta(seconds=15)
    success = False
    try:
        await broker(TASK, (str(execution.identity),), str(execution.identity))
        success = True
    except Exception:
        pass
    async with m.sessions.begin() as session:
        row, _, _ = await execution.row(session, pins=False)
        if row.state in {"succeeded", "failed", "unavailable"} or row.delivery_fence != token:
            return
        row.delivery_state = "published" if success else "retry"
        row.available_at = m.now() + timedelta(
            seconds=15 if success else min(30, 2**row.delivery_attempts)
        )
        row.delivery_lease_at = None


async def reconcile_tests(sessions, settings, broker):
    if not settings.llm_management_enabled or not settings.llm_connection_tests_enabled:
        return
    async with sessions.begin() as session:
        identities = (
            await session.scalars(
                select(Job.id)
                .where(
                    Job.job_type == "LLM_CONNECTION_TEST", Job.status.in_(("QUEUED", "IN_PROGRESS"))
                )
                .order_by(Job.updated_at, Job.id)
                .limit(100)
            )
        ).all()
    for identity in identities:
        try:
            m = await management_for_job(sessions, settings, identity)
            await publish_test(TestExecution(m, identity), broker)
        except (ManagementError, PermissionError):
            continue


async def celery_test_broker(app, task, args, identity):
    async with asyncio.timeout(10):
        await asyncio.to_thread(
            app.send_task,
            task,
            args=list(args),
            task_id=identity,
            serializer="json",
            ignore_result=True,
            retry=False,
        )
