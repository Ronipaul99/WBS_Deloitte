"""Step 2 isolated contract/storage tests. Invoke pytest with --noconftest."""

import pytest
import pytest_asyncio
from agent_schema_fixtures import (
    HEAD,
    NOW,
    OLD_HEAD,
    ROOT,
    access,
    checkpoint,
    content,
    migrate,
    scope,
    seed_agents,
    seed_legacy,
    uid,
)
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.agent_types import WorkflowState, workflow_job_status
from app.models.agent_workflows import (
    AgentCheckpoint,
    AgentStepRun,
    SummaryApprovalEvent,
    SummaryEvidence,
    SummaryRevision,
    WorkflowDispatchOutbox,
)
from app.models.domain import DocumentSummary, TenantMembership
from app.models.llm import LlmCredentialVersion, LlmModelProfileVersion
from app.services.agents.persistence_types import StoredArtifact, safe_json
from app.services.agents.repository import (
    LegacySummaryRepository,
    StaleRevisionError,
    WorkflowRepository,
)
from app.services.llm.repository import LlmRepository
from migrations.versions import f8c2a6d903b1_add_agent_persistence as migration


@pytest_asyncio.fixture
async def storage():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as session:
        await seed_legacy(session)
        await seed_agents(session)
    yield factory
    await engine.dispose()


def test_new_head_and_relational_scope_constraints():
    config = Config()
    config.set_main_option("script_location", str(ROOT / "migrations"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["e53c7a19b402"]
    assert script.get_revision("b7e31d95a204").down_revision == HEAD
    assert migration.down_revision == OLD_HEAD
    assert set(migration.PROTECTED_TABLES) <= set(Base.metadata.tables)
    for name in migration.PROTECTED_TABLES:
        table = Base.metadata.tables[name]
        assert not table.c.tenant_id.nullable
        assert all(fk.ondelete != "CASCADE" for fk in table.foreign_key_constraints)
    for name in ("agent_step_runs", "agent_checkpoints", "summary_revisions", "summary_evidence"):
        assert "workflow_run_id" in Base.metadata.tables[name].c
    assert "ciphertext" in Base.metadata.tables["llm_credential_versions"].c
    assert not {"plaintext", "api_key", "password", "pickle", "messages"} & set(
        Base.metadata.tables["llm_credential_versions"].c.keys()
    )


@pytest.mark.parametrize(
    "state,job_status",
    [
        ("queued", "QUEUED"),
        ("running", "IN_PROGRESS"),
        ("review_required", "COMPLETED"),
        ("partial", "FAILED"),
        ("quality_blocked", "FAILED"),
        ("stale", "FAILED"),
        ("failed", "FAILED"),
        ("cancelled", "CANCELLED"),
    ],
)
def test_job_mapping_never_equates_generation_and_approval(state, job_status):
    assert workflow_job_status(state) == job_status
    assert "approved" not in {item.value for item in WorkflowState}
    with pytest.raises(ValueError):
        workflow_job_status("approved")


@pytest.mark.parametrize(
    "field",
    [
        "api_key",
        "Authorization",
        "messages",
        "raw_response",
        "chain-of-thought",
        "reasoning",
        "password",
    ],
)
def test_nested_storage_secret_fields_rejected(field):
    with pytest.raises(ValueError):
        safe_json({"artifact": [{field: "SYNTHETIC_SENTINEL"}]})


def test_json_bounds_nesting_finite_values_and_artifact_schema():
    for invalid in ({"x": float("nan")}, {"x": object()}, {"x": "x" * 100}):
        with pytest.raises(ValueError):
            safe_json(invalid, 64)
    deep = {}
    for _ in range(18):
        deep = {"x": deep}
    with pytest.raises(ValueError):
        safe_json(deep)
    with pytest.raises(ValueError):
        StoredArtifact.model_validate({"kind": "facts.v1", "payload": {"messages": []}})


@pytest.mark.asyncio
async def test_repository_permissions_legacy_reads_and_scoped_credential_lookup(storage):
    async with storage.begin() as session:
        legacy = await LegacySummaryRepository(session, access(29)).get(uid(3))
        assert legacy.summary_text == "Preserved legacy text"
        assert legacy.content_origin == "legacy_unverified"
        assert legacy.active_revision_id is None
        assert await LegacySummaryRepository(session, access(109, 101)).get(uid(3)) is None
        for user in (19, 29):
            with pytest.raises(PermissionError):
                await LlmRepository(session, access(user)).credential_version(uid(5), uid(50))
        assert await LlmRepository(session, access()).credential_version(uid(5), uid(50)) is None
        assert await LlmRepository(session, access(19)).approved_profiles() == []
        with pytest.raises(PermissionError):
            await LlmRepository(session, access(29)).approved_profiles()
        assert await LlmRepository(session, access(109, 101)).connection(uid(5)) is None


@pytest.mark.asyncio
async def test_repository_needs_transaction_and_denies_unknown_role(storage):
    async with storage() as session:
        with pytest.raises(RuntimeError):
            await LlmRepository(session, access()).connection(uid(5))
    async with storage.begin() as session:
        membership = await session.get(TenantMembership, (uid(1), uid(19)))
        membership.role = "UNKNOWN"
        await session.flush()
        with pytest.raises(PermissionError):
            await LlmRepository(session, access(19)).approved_profiles()


@pytest.mark.asyncio
async def test_workflow_bound_checkpoint_and_audit_permissions(storage):
    async with storage.begin() as session:
        repository = WorkflowRepository(session, access(), scope())
        assert (await repository.checkpoint(uid(40))).sequence == 1
        with pytest.raises(PermissionError):
            await WorkflowRepository(session, access(), scope(88)).checkpoint(uid(40))
        with pytest.raises(PermissionError):
            await WorkflowRepository(session, access(29), scope()).checkpoint(uid(40))
        with pytest.raises(PermissionError):
            await WorkflowRepository(session, access(19), scope()).usage_audit()
        assert await repository.usage_audit() == []
        wrong = checkpoint(41, 2)
        wrong.workflow_run_id = uid(88)
        with pytest.raises(PermissionError):
            await repository.add(wrong)


@pytest.mark.asyncio
async def test_active_pointer_compare_and_swap_and_revision_approval(storage):
    async with storage.begin() as session:
        repo = WorkflowRepository(session, access(), scope())
        await repo.set_active_revision(uid(20), uid(10), 0)
        with pytest.raises(StaleRevisionError):
            await repo.set_active_revision(uid(20), uid(10), 0)
        await repo.append_approval_event(
            SummaryApprovalEvent(
                id=uid(60),
                tenant_id=uid(1),
                workflow_run_id=uid(8),
                summary_id=uid(20),
                document_id=uid(3),
                revision_id=uid(10),
                reviewer_id=uid(9),
                expected_version=1,
                decision="approved",
                decided_at=NOW,
            )
        )
        summary = await session.get(DocumentSummary, uid(20))
        assert summary.is_approved and summary.revision_version == 2
        assert (await session.get(SummaryRevision, uid(10))).content == content()
        with pytest.raises(StaleRevisionError):
            await repo.append_approval_event(
                SummaryApprovalEvent(
                    id=uid(61),
                    tenant_id=uid(1),
                    workflow_run_id=uid(8),
                    summary_id=uid(20),
                    document_id=uid(3),
                    revision_id=uid(10),
                    reviewer_id=uid(9),
                    expected_version=1,
                    decision="rejected",
                    decided_at=NOW,
                )
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model,index,field,value",
    [
        (AgentCheckpoint, 40, "node", "tampered"),
        (SummaryRevision, 10, "quality", "stale"),
        (LlmModelProfileVersion, 21, "version", 2),
    ],
)
async def test_immutable_records_reject_updates(storage, model, index, field, value):
    async with storage() as session:
        async with session.begin():
            row = await session.get(model, uid(index))
            setattr(row, field, value)
            with pytest.raises(ValueError, match="append-only"):
                await session.flush()
            await session.rollback()


@pytest.mark.asyncio
async def test_duplicate_checkpoint_outbox_and_step_identities(storage):
    factories = [
        lambda index: checkpoint(index),
        lambda index: WorkflowDispatchOutbox(
            id=uid(index),
            tenant_id=uid(1),
            workflow_run_id=uid(8),
            job_id=uid(31),
            task_name="synthetic",
            continuation=0,
            available_at=NOW,
        ),
        lambda index: AgentStepRun(
            id=uid(index),
            tenant_id=uid(1),
            workflow_run_id=uid(8),
            node="synthetic",
            batch=0,
            attempt=1,
            input_sha256="a" * 64,
            state="pending",
            artifact={"kind": "facts.v1", "payload": {}},
            usage={"source": "unknown"},
        ),
    ]
    for factory in factories:
        async with storage() as session:
            async with session.begin():
                if not isinstance(factory(71), AgentCheckpoint):
                    session.add(factory(71))
                    await session.flush()
                session.add(factory(72))
                with pytest.raises(IntegrityError):
                    await session.flush()
                await session.rollback()


@pytest.mark.asyncio
async def test_cross_tenant_foreign_key_for_credentials(storage):
    async with storage() as session:
        async with session.begin():
            session.add(
                LlmCredentialVersion(
                    id=uid(50),
                    tenant_id=uid(101),
                    connection_id=uid(5),
                    version=1,
                    ciphertext=b"x" * 32,
                    nonce=b"n" * 12,
                    key_version="synthetic",
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()


@pytest.mark.asyncio
async def test_evidence_claim_locator_binding_and_append_only(storage):
    async with storage.begin() as session:
        locator = content()["evidence"][0]
        row = SummaryEvidence(
            id=uid(80),
            tenant_id=uid(1),
            workflow_run_id=uid(8),
            revision_id=uid(10),
            project_id=uid(2),
            document_id=uid(3),
            processing_run_id=uid(4),
            chunk_id=uid(14),
            evidence_id=uid(13),
            claim_id=uid(11),
            chunk_sha256=locator["chunk_sha256"],
            locator=locator,
        )
        await WorkflowRepository(session, access(), scope()).add(row)
    async with storage() as session, session.begin():
        row = await session.get(SummaryEvidence, uid(80))
        row.claim_id = uid(12)
        with pytest.raises(ValueError, match="append-only"):
            await session.flush()
        await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["quote", "claim", "snapshot_scope"])
async def test_evidence_rejects_invalid_locators_and_claims(storage, invalid):
    locator = content()["evidence"][0]
    if invalid == "quote":
        locator["exact_quote"] = "x" * len(locator["exact_quote"])
    if invalid == "snapshot_scope":
        locator["scope"]["tenant_id"] = str(uid(101))
    row = SummaryEvidence(
        id=uid(80),
        tenant_id=uid(1),
        workflow_run_id=uid(8),
        revision_id=uid(10),
        project_id=uid(2),
        document_id=uid(3),
        processing_run_id=uid(4),
        chunk_id=uid(14),
        evidence_id=uid(13),
        claim_id=uid(12) if invalid == "claim" else uid(11),
        chunk_sha256=locator["chunk_sha256"],
        locator=locator,
    )
    async with storage() as session, session.begin():
        session.add(row)
        with pytest.raises(ValueError):
            await session.flush()
        await session.rollback()


@pytest.mark.asyncio
async def test_fixture_profile_cannot_be_enabled(storage):
    from app.models.llm import LlmModelProfile

    async with storage() as session, session.begin():
        profile = await session.get(LlmModelProfile, uid(6))
        profile.active_version_id = uid(21)
        profile.enabled = True
        with pytest.raises(ValueError, match="live qualification"):
            await session.flush()
        await session.rollback()


@pytest.mark.asyncio
async def test_stale_and_deleting_sources_cannot_publish(storage):
    from app.models.domain import Document

    async with storage.begin() as session:
        document = await session.get(Document, uid(3))
        document.current_processing_run_id = None
        await session.flush()
        with pytest.raises(StaleRevisionError):
            await WorkflowRepository(session, access(), scope()).set_active_revision(
                uid(20), uid(10), 0
            )


@pytest.mark.asyncio
async def test_approval_events_and_completed_steps_are_immutable(storage):
    async with storage.begin() as session:
        repo = WorkflowRepository(session, access(), scope())
        await repo.set_active_revision(uid(20), uid(10), 0)
        await repo.append_approval_event(
            SummaryApprovalEvent(
                id=uid(60),
                tenant_id=uid(1),
                workflow_run_id=uid(8),
                summary_id=uid(20),
                document_id=uid(3),
                revision_id=uid(10),
                reviewer_id=uid(9),
                expected_version=1,
                decision="approved",
                decided_at=NOW,
            )
        )
        await repo.add(
            AgentStepRun(
                id=uid(70),
                tenant_id=uid(1),
                workflow_run_id=uid(8),
                node="synthetic",
                batch=0,
                attempt=1,
                input_sha256="a" * 64,
                state="completed",
                artifact={"kind": "facts.v1", "payload": {}},
                usage={"source": "unknown"},
                completed_at=NOW,
            )
        )
    for model, index, field, value in (
        (SummaryApprovalEvent, 60, "decision", "rejected"),
        (AgentStepRun, 70, "state", "pending"),
    ):
        async with storage() as session, session.begin():
            row = await session.get(model, uid(index))
            setattr(row, field, value)
            with pytest.raises(ValueError):
                await session.flush()
            await session.rollback()


def test_sqlite_migration_upgrade_legacy_preservation_downgrade_and_reupgrade():
    # SQLite migration compatibility only. This is NOT PostgreSQL RLS evidence.
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        migrate(connection, target=OLD_HEAD)
        connection.execute(
            text(
                "INSERT INTO tenants (id,name,slug,is_active) VALUES (:id,'Legacy','legacy',true)"
            ),
            {"id": uid(1).hex},
        )
        # Historical schema has no new columns; use raw synthetic legacy rows.
        connection.execute(
            text(
                "INSERT INTO users (id,external_subject,email,display_name,is_active) "
                "VALUES (:id,'legacy','legacy@example.invalid','Legacy',true)"
            ),
            {"id": uid(9).hex},
        )
        connection.execute(
            text(
                "INSERT INTO projects (id,tenant_id,created_by,name,status) "
                "VALUES (:id,:tenant,:user,'Legacy','ACTIVE')"
            ),
            {"id": uid(2).hex, "tenant": uid(1).hex, "user": uid(9).hex},
        )
        connection.execute(
            text(
                "INSERT INTO documents (id,tenant_id,project_id,uploaded_by,kind,"
                "file_name,content_type,size_bytes,storage_key) VALUES (:id,:tenant,:project,:user,"
                "'PROJECT','legacy.pdf','application/pdf',1,'legacy')"
            ),
            {"id": uid(3).hex, "tenant": uid(1).hex, "project": uid(2).hex, "user": uid(9).hex},
        )
        connection.execute(
            text(
                "INSERT INTO document_summaries (id,tenant_id,document_id,summary_text,"
                "key_points,requirements,is_approved) VALUES (:id,:tenant,:doc,'Legacy preserved',"
                "'[]','[]',true)"
            ),
            {"id": uid(20).hex, "tenant": uid(1).hex, "doc": uid(3).hex},
        )
        before = connection.execute(text("SELECT * FROM documents")).mappings().one()
        connection.execute(
            text(
                "INSERT INTO jobs (id,tenant_id,project_id,created_by,job_type,status,"
                "progress,request_payload,result_payload) VALUES (:id,:tenant,:project,:user,"
                "'DOCUMENT_INGESTION','COMPLETED',100,'{}','{}')"
            ),
            {"id": uid(30).hex, "tenant": uid(1).hex, "project": uid(2).hex, "user": uid(9).hex},
        )
        connection.execute(
            text(
                "INSERT INTO document_processing_runs "
                "(id,tenant_id,project_id,document_id,job_id,status,document_content_sha256,extractor_name,"
                "extractor_version,embedding_provider,embedding_model,embedding_dimensions,"
                "page_count,worksheet_count,block_count,chunk_count) VALUES "
                "(:id,:tenant,:project,:doc,:job,'COMPLETED',:hash,'legacy','1','fastembed',"
                "'synthetic',384,1,0,1,1)"
            ),
            {
                "id": uid(4).hex,
                "tenant": uid(1).hex,
                "project": uid(2).hex,
                "doc": uid(3).hex,
                "job": uid(30).hex,
                "hash": "a" * 64,
            },
        )
        connection.execute(
            text(
                "INSERT INTO document_chunks (id,tenant_id,project_id,document_id,"
                "processing_run_id,ordinal,token_count,content,content_sha256,block_type,heading_path,"
                "source_metadata,embedding) VALUES (:id,:tenant,:project,:doc,:run,"
                "0,1,'legacy chunk',"
                ":hash,'paragraph','[]','{}',:vector)"
            ),
            {
                "id": uid(14).hex,
                "tenant": uid(1).hex,
                "project": uid(2).hex,
                "doc": uid(3).hex,
                "run": uid(4).hex,
                "hash": "b" * 64,
                "vector": "[1" + ",0" * 383 + "]",
            },
        )
        before_vectors = connection.execute(text("SELECT * FROM document_chunks")).mappings().all()
        before_runs = (
            connection.execute(text("SELECT * FROM document_processing_runs")).mappings().all()
        )
        migrate(connection, start=OLD_HEAD)
        after = connection.execute(text("SELECT * FROM documents")).mappings().one()
        assert dict(before) == dict(after)
        assert (
            before_vectors
            == connection.execute(text("SELECT * FROM document_chunks")).mappings().all()
        )
        assert (
            before_runs
            == connection.execute(text("SELECT * FROM document_processing_runs")).mappings().all()
        )
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        row = connection.execute(text("SELECT * FROM document_summaries")).mappings().one()
        assert row["summary_text"] == "Legacy preserved" and row["is_approved"]
        assert row["content_origin"] == "legacy_unverified" and row["active_revision_id"] is None
        assert connection.scalar(text("SELECT count(*) FROM summary_revisions")) == 0
        migrate(connection, start=OLD_HEAD, downgrade=True)
        assert "summary_revisions" not in inspect(connection).get_table_names()
        migrate(connection, start=OLD_HEAD)
        assert "summary_revisions" in inspect(connection).get_table_names()
    engine.dispose()


def test_postgres_security_statements_cover_every_new_table(monkeypatch):
    statements = []
    bind = type("Bind", (), {"dialect": __import__("sqlalchemy").dialects.postgresql.dialect()})()
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    monkeypatch.setattr(migration.op, "execute", lambda sql: statements.append(str(sql)))
    monkeypatch.setattr(migration.op, "create_check_constraint", lambda *args: None)
    migration._protect(("runtime", "migration_owner"))
    for table in migration.PROTECTED_TABLES:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in statements
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in statements
        assert any(
            f"CREATE POLICY {table}_scope" in sql and "WITH CHECK" in sql for sql in statements
        )
    assert any("app.agent_workflow_run_id" in sql for sql in statements)
    assert "SECURITY DEFINER" not in "\n".join(statements)


@pytest.mark.asyncio
async def test_populated_sqlite_schema_refuses_destructive_downgrade(storage):
    async with storage() as session, session.begin():
        connection = await session.connection()
        with pytest.raises(RuntimeError, match="forward fix"):
            await connection.run_sync(lambda conn: migrate(conn, start=OLD_HEAD, downgrade=True))
        assert await session.scalar(select(AgentCheckpoint.id)) == uid(40)
