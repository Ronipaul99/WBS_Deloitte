"""Synthetic Step 2 rows; no application settings or configured database access."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.models.agent_workflows import AgentCheckpoint, AgentWorkflowRun, SummaryRevision
from app.models.domain import (
    Document,
    DocumentChunk,
    DocumentProcessingRun,
    DocumentSummary,
    Job,
    Project,
    Tenant,
    TenantMembership,
    User,
)
from app.models.llm import LlmConnection, LlmModelProfile, LlmModelProfileVersion
from app.services.agents.contracts import SourceScope
from app.services.agents.repository import WorkflowStorageScope
from app.services.agents.scoped_storage import StorageAccess

ROOT = Path(__file__).resolve().parents[1]
OLD_HEAD = "e71c4a9b203d"
HEAD = "f8c2a6d903b1"


def uid(number):
    return UUID(int=number)


def content():
    return json.loads(
        (ROOT / "tests/agent_contract_fixtures/summary.json").read_text(encoding="utf-8")
    )


def access(user=9, tenant=1):
    return StorageAccess(uid(tenant), uid(user))


def scope(run=8):
    return WorkflowStorageScope(
        SourceScope.model_validate(content()["workflow"]["scope"]), uid(run)
    )


def migrate(connection, *, target=HEAD, start=None, runtime=None, owner=None, downgrade=False):
    """Run frozen revisions with the supplied disposable connection, never env.py."""
    config = Config()
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.attributes.update(runtime_database_role=runtime, migration_database_role=owner)
    script = ScriptDirectory.from_config(config)
    context = MigrationContext.configure(
        connection, environment_context=SimpleNamespace(config=config)
    )
    revisions = list(script.iterate_revisions(target, start))
    if not downgrade:
        revisions.reverse()
    with Operations.context(context):
        for revision in revisions:
            if downgrade:
                revision.module.downgrade()
            else:
                revision.module.upgrade()
    context.stamp(script, start if downgrade else target)


async def seed_legacy(session, *, with_summary=True):
    session.add_all(
        [
            Tenant(id=uid(1), name="Synthetic A", slug="synthetic-a"),
            Tenant(id=uid(101), name="Synthetic B", slug="synthetic-b"),
        ]
    )
    session.add_all(
        [
            User(
                id=uid(index),
                external_subject=f"synthetic-{index}",
                email=f"synthetic-{index}@example.invalid",
                display_name="Synthetic",
            )
            for index in (9, 19, 29, 109)
        ]
    )
    await session.flush()
    for user, tenant, role in (
        (9, 1, "ADMIN"),
        (19, 1, "EDITOR"),
        (29, 1, "VIEWER"),
        (109, 101, "ADMIN"),
    ):
        session.add(TenantMembership(tenant_id=uid(tenant), user_id=uid(user), role=role))
    session.add(Project(id=uid(2), tenant_id=uid(1), created_by=uid(9), name="Synthetic"))
    await session.flush()
    session.add(
        Document(
            id=uid(3),
            tenant_id=uid(1),
            project_id=uid(2),
            uploaded_by=uid(9),
            file_name="synthetic.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key="synthetic/not-a-real-object",
            content_sha256="a" * 64,
        )
    )
    session.add_all(
        [
            Job(
                id=uid(index),
                tenant_id=uid(1),
                project_id=uid(2),
                created_by=uid(9),
                job_type=kind,
                status="COMPLETED",
            )
            for index, kind in ((30, "DOCUMENT_INGESTION"), (31, "DOCUMENT_SUMMARY"))
        ]
    )
    await session.flush()
    session.add(
        DocumentProcessingRun(
            id=uid(4),
            tenant_id=uid(1),
            project_id=uid(2),
            document_id=uid(3),
            job_id=uid(30),
            status="COMPLETED",
            document_content_sha256="a" * 64,
            extractor_name="synthetic",
            extractor_version="1",
            chunker_version="1",
            embedding_provider="fastembed",
            embedding_model="synthetic",
            embedding_model_revision="b" * 40,
            embedding_dimensions=384,
            embedding_formatting_version="v1",
            page_count=1,
            block_count=1,
            chunk_count=1,
        )
    )
    await session.flush()
    document = await session.get(Document, uid(3))
    document.current_processing_run_id = uid(4)
    document.processing_status = "COMPLETED"
    chunk = "Synthetic tender \U0001f31e\nIssuer: Example Energy Board.\nCapacity: 8 MW."
    session.add(
        DocumentChunk(
            id=uid(14),
            tenant_id=uid(1),
            project_id=uid(2),
            document_id=uid(3),
            processing_run_id=uid(4),
            ordinal=0,
            token_count=20,
            content=chunk,
            content_sha256=content()["evidence"][0]["chunk_sha256"],
            block_type="canonical_chunk",
            page_number=1,
            heading_path=[],
            source_metadata={},
            embedding=[1.0] + [0.0] * 383,
        )
    )
    if with_summary:
        session.add(
            DocumentSummary(
                id=uid(20),
                tenant_id=uid(1),
                document_id=uid(3),
                summary_text="Preserved legacy text",
                key_points=["legacy"],
                requirements=[],
                is_approved=False,
            )
        )
    await session.flush()


async def seed_agents(session):
    summary = content()
    session.add(
        LlmConnection(
            id=uid(5),
            tenant_id=uid(1),
            name="Synthetic disabled",
            provider="openai_compatible",
            protocol="chat_completions",
            endpoint_policy={"host": "example.invalid", "path_prefix": "/v1"},
        )
    )
    await session.flush()
    session.add(
        LlmModelProfile(id=uid(6), tenant_id=uid(1), connection_id=uid(5), name="Synthetic")
    )
    await session.flush()
    session.add(
        LlmModelProfileVersion(
            id=uid(21),
            tenant_id=uid(1),
            connection_id=uid(5),
            profile_id=uid(6),
            version=1,
            snapshot=summary["workflow"]["profile"],
        )
    )
    await session.flush()
    session.add(
        AgentWorkflowRun(
            id=uid(8),
            tenant_id=uid(1),
            project_id=uid(2),
            document_id=uid(3),
            processing_run_id=uid(4),
            job_id=uid(31),
            requested_by=uid(9),
            profile_id=uid(6),
            connection_id=uid(5),
            profile_version_id=uid(21),
            source_sha256="a" * 64,
            input_snapshot=summary["workflow"],
            budget={"max_calls": 10, "max_total_tokens": 10000, "timeout_seconds": 60},
            request_sequence=1,
            state="review_required",
        )
    )
    await session.flush()
    legacy = await session.get(DocumentSummary, uid(20))
    legacy.latest_request_sequence = 1
    session.add(revision())
    session.add(checkpoint())
    await session.flush()


def revision():
    return SummaryRevision(
        id=uid(10),
        tenant_id=uid(1),
        workflow_run_id=uid(8),
        summary_id=uid(20),
        project_id=uid(2),
        document_id=uid(3),
        processing_run_id=uid(4),
        version=1,
        content=content(),
        quality="review_required",
    )


def checkpoint(index=40, sequence=1):
    return AgentCheckpoint(
        id=uid(index),
        tenant_id=uid(1),
        workflow_run_id=uid(8),
        sequence=sequence,
        node="synthetic",
        input_sha256="a" * 64,
        artifact={"kind": "facts.v1", "payload": {"facts": []}},
    )


NOW = datetime(2026, 10, 27, tzinfo=UTC)
