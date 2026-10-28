"""Real PostgreSQL contention/FK/RLS checks; never use the application's DATABASE_URL."""

import asyncio
import os
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.datastructures import Headers, UploadFile

from app.core.config import Settings
from app.core.permissions import permissions_for_role
from app.db.base import Base
from app.db.session import set_local_tenant_context
from app.models.document_workflows import DocumentContentClaim
from app.models.domain import Document, Project, Tenant, TenantMembership, User
from app.services.document_content import upload_or_reuse
from app.services.storage import LocalObjectStorage

URL = os.getenv("DEDUP_TEST_POSTGRES_URL")
RUNTIME_URL = os.getenv("DEDUP_TEST_POSTGRES_RUNTIME_URL")
READY = bool(
    URL and os.getenv("DEDUP_TEST_DISPOSABLE_ACK") == "I_ACKNOWLEDGE_THIS_DATABASE_IS_DISPOSABLE"
)
pytestmark = pytest.mark.skipif(
    not READY, reason="Disposable PostgreSQL URL and acknowledgement required"
)
CONTENT = b"Task,Description\n1,Concurrency verification\n"


@pytest.fixture
async def postgres(tmp_path):
    schema = "dedup_test_" + uuid4().hex
    url = Settings._as_async_sqlalchemy_url(URL)
    database = make_url(url).database or ""
    if not (database.startswith("wbs_upload_test_") or database == "wbs_fullstack"):
        pytest.fail("PostgreSQL verification requires an explicitly named disposable test database")
    admin = create_async_engine(url, hide_parameters=True)
    async with admin.begin() as connection:
        await connection.execute(text('CREATE SCHEMA "' + schema + '"'))
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    engine = create_async_engine(
        url,
        hide_parameters=True,
        connect_args={"server_settings": {"search_path": schema + ",public"}},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            tenant = Tenant(name="Disposable tenant", slug="dedup-test")
            user = User(
                external_subject="dedup-test", email="test@example.com", display_name="Test"
            )
            db.add_all([tenant, user])
            await db.flush()
            project = Project(tenant_id=tenant.id, created_by=user.id, name="Contention test")
            db.add(project)
            await db.flush()
            db.add(TenantMembership(tenant_id=tenant.id, user_id=user.id, role="ADMIN"))
            await db.commit()
        settings = Settings(
            _env_file=None,
            upload_root=tmp_path / "objects",
            storage_backend="local",
            document_workflow_resume_enabled=True,
            document_upload_reuse_enabled=True,
        )
        context = SimpleNamespace(
            tenant=tenant, user=user, permissions=permissions_for_role("ADMIN")
        )
        yield SimpleNamespace(
            schema=schema,
            engine=engine,
            factory=factory,
            settings=settings,
            context=context,
            project=project,
        )
    finally:
        await engine.dispose()
        # Only the generated disposable schema is removed.
        assert schema.startswith("dedup_test_") and len(schema) == 43
        async with admin.begin() as connection:
            await connection.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))
        await admin.dispose()


async def test_simultaneous_uploads_publish_one_object_and_document(postgres):
    entered, release = asyncio.Event(), asyncio.Event()

    class PausedStorage(LocalObjectStorage):
        saves = 0

        async def save(self, *args, **kwargs):
            self.saves += 1
            entered.set()
            await asyncio.wait_for(release.wait(), timeout=15)
            return await super().save(*args, **kwargs)

    storage = PausedStorage(postgres.settings)

    async def submit():
        file = UploadFile(
            BytesIO(CONTENT), filename="scope.csv", headers=Headers({"content-type": "text/csv"})
        )
        try:
            async with postgres.factory() as db:
                return await upload_or_reuse(
                    db,
                    context=postgres.context,
                    project_id=postgres.project.id,
                    file=file,
                    suffix=".csv",
                    content_type="text/csv",
                    storage=storage,
                    settings=postgres.settings,
                )
        finally:
            await file.close()

    first = asyncio.create_task(submit())
    try:
        await asyncio.wait_for(entered.wait(), timeout=15)
        losing = await submit()
        assert losing[0] == "UPLOAD_PENDING"
        release.set()
        created = await asyncio.wait_for(first, timeout=15)
        repeated = await submit()
        assert created[0] == "CREATED" and repeated[0] == "REUSED"
        assert repeated[1].id == created[1].id
        assert storage.saves == 1
        async with postgres.factory() as db:
            assert await db.scalar(select(func.count()).select_from(Document)) == 1
    finally:
        release.set()
        if not first.done():
            await first


async def test_database_rejects_cross_tenant_document_claim_reference(postgres):
    async with postgres.factory() as db:
        other = Tenant(name="Other tenant", slug="other")
        db.add(other)
        await db.flush()
        document = Document(
            tenant_id=postgres.context.tenant.id,
            project_id=postgres.project.id,
            uploaded_by=postgres.context.user.id,
            kind="PROJECT",
            file_name="test.csv",
            content_type="text/csv",
            size_bytes=1,
            storage_key="disposable-object",
        )
        db.add(document)
        await db.commit()
        db.add(
            DocumentContentClaim(
                tenant_id=other.id,
                sha256="a" * 64,
                size_bytes=1,
                state="READY",
                document_id=document.id,
                project_id=postgres.project.id,
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


@pytest.mark.skipif(
    not RUNTIME_URL, reason="Restricted disposable PostgreSQL runtime role URL required"
)
async def test_runtime_rls_requires_matching_tenant_context(postgres):
    from datetime import UTC, datetime, timedelta

    runtime = create_async_engine(
        Settings._as_async_sqlalchemy_url(RUNTIME_URL),
        hide_parameters=True,
        connect_args={"server_settings": {"search_path": postgres.schema + ",public"}},
    )
    try:
        async with runtime.connect() as connection:
            role = await connection.scalar(text("SELECT current_user"))
            unsafe = await connection.scalar(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
            )
            assert unsafe is False, "RLS verification requires a restricted runtime role"
        quote = postgres.engine.dialect.identifier_preparer.quote
        async with postgres.engine.begin() as connection:
            await connection.execute(
                text(f"GRANT USAGE ON SCHEMA {quote(postgres.schema)} TO {quote(role)}")
            )
            await connection.execute(
                text("ALTER TABLE document_content_claims ENABLE ROW LEVEL SECURITY")
            )
            await connection.execute(
                text("ALTER TABLE document_content_claims FORCE ROW LEVEL SECURITY")
            )
            expression = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
            await connection.execute(
                text(
                    f"CREATE POLICY tenant_isolation ON document_content_claims "
                    f"USING ({expression}) WITH CHECK ({expression})"
                )
            )
            await connection.execute(
                text(f"GRANT SELECT ON document_content_claims TO {quote(role)}")
            )
        async with postgres.factory() as db:
            await db.begin()
            await set_local_tenant_context(db, postgres.context.tenant.id)
            db.add(
                DocumentContentClaim(
                    tenant_id=postgres.context.tenant.id,
                    sha256="b" * 64,
                    size_bytes=1,
                    state="RESERVED",
                    owner_token=uuid4(),
                    lease_expires_at=datetime.now(UTC) + timedelta(minutes=2),
                )
            )
            await db.commit()
        async with async_sessionmaker(runtime)() as db:
            assert await db.scalar(select(func.count()).select_from(DocumentContentClaim)) == 0
            await set_local_tenant_context(db, postgres.context.tenant.id)
            assert await db.scalar(select(func.count()).select_from(DocumentContentClaim)) == 1
            await set_local_tenant_context(db, uuid4())
            assert await db.scalar(select(func.count()).select_from(DocumentContentClaim)) == 0
    finally:
        await runtime.dispose()
