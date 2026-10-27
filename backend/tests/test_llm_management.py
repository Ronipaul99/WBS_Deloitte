"""Isolated Step 6 synthetic storage/API tests; --noconftest is mandatory."""

from datetime import timedelta
from uuid import UUID

import pytest
import pytest_asyncio
from agent_schema_fixtures import NOW, access, seed_agents, seed_legacy, uid
from llm_security_fixtures import SENTINEL, endpoint, keys
from pydantic import SecretStr, ValidationError
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.auth import AuthEvent
from app.models.domain import Job
from app.models.llm import LlmConnection, LlmConnectionTest, LlmModelProfileVersion
from app.schemas.llm import (
    ConnectionCreate,
    ConnectionUpdate,
    CredentialUpdate,
    ProfileCreate,
    ProfileSettings,
    ProfileState,
    ProfileUpdate,
)
from app.schemas.llm import (
    TestSubmit as Submit,
)
from app.services.llm.credentials import CredentialChange
from app.services.llm.management import ModelManagement
from app.services.llm.management_types import ManagementError
from app.services.llm.test_execution import ProbeBudget
from app.services.llm.test_execution import TestExecution as Execution
from app.services.llm.test_worker import publish_test


@pytest_asyncio.fixture(name="manager")
async def manager(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'management.db').as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(conn, record):
        conn.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        await seed_legacy(session)
        await seed_agents(session)
    endpoints, _ = endpoint()
    service = ModelManagement(
        sessions, access(), endpoints, keys(), tests_enabled=True, now=lambda: NOW
    )
    yield service
    await engine.dispose()


async def saved(service):
    c = await service.save_connection(
        ConnectionCreate(
            name="Synthetic gateway",
            provider="openai_compatible",
            approval_id=uid(70),
            enabled=True,
            credential=CredentialChange(action="replace", secret=SecretStr(SENTINEL)),
        )
    )
    p = await service.save_profile(
        ProfileCreate(
            name="Manual model",
            connection_id=UUID(c["id"]),
            model_id="synthetic-model-not-a-live-model",
        )
    )
    return c, p


def authorize_test(service, c, p):
    fp = p["candidate_fingerprint"]
    service.permits[fp] = {
        "connection_id": c["id"],
        "configuration_fingerprint": fp,
        "expires_at": NOW + timedelta(hours=1),
        "max_calls": 8,
        "max_tokens": 50000,
        "max_cost_usd": "1",
        "input_usd_per_million": "0",
        "output_usd_per_million": "0",
        "request_fee_usd": "0",
        "pricing_reviewed_at": NOW,
        "approved_synthetic_only": True,
    }


async def submitted(service):
    c, p = await saved(service)
    authorize_test(service, c, p)
    row = await service.submit_test(
        UUID(c["id"]),
        Submit(
            profile_id=UUID(p["id"]),
            expected_profile_revision=p["revision"],
            expected_connection_revision=c["revision"],
            acknowledge_cost=True,
            plan={"cases": ["authentication", "model_access", "structured_output", "usage"]},
        ),
    )
    return c, p, row


@pytest.mark.asyncio
async def test_credential_preserve_cas_rotation_clear_and_secret_exclusion(manager):
    c, p = await saved(manager)
    assert SENTINEL not in str(c) + str(p)
    identity = UUID(c["id"])
    async with manager.sessions.begin() as session:
        initial = (await session.get(LlmConnection, identity)).active_credential_id
    await manager.save_connection(ConnectionUpdate(expected_revision=1, name="Renamed"), identity)
    async with manager.sessions.begin() as session:
        assert (await session.get(LlmConnection, identity)).active_credential_id == initial
    with pytest.raises(ManagementError, match="stale_revision"):
        await manager.save_connection(ConnectionUpdate(expected_revision=1), identity)
    rotated = await manager.credential(
        identity, CredentialUpdate(expected_revision=2, change=CredentialChange(action="rotate"))
    )
    assert rotated["configured"] and rotated["revision"] == 3
    cleared = await manager.credential(
        identity, CredentialUpdate(expected_revision=3, change=CredentialChange(action="clear"))
    )
    assert not cleared["configured"] and not cleared["enabled"]
    async with manager.sessions.begin() as session:
        assert SENTINEL not in str((await session.scalars(select(AuthEvent.details))).all())


@pytest.mark.asyncio
@pytest.mark.parametrize("user,tenant", [(19, 1), (29, 1), (109, 101)])
async def test_permissions_and_cross_tenant_ids(manager, user, tenant):
    c, _ = await saved(manager)
    other = ModelManagement(manager.sessions, access(user, tenant), manager.endpoints, manager.keys)
    if tenant == 101:
        assert await other.connections() == []
        with pytest.raises(ManagementError, match="not_found"):
            await other.save_connection(ConnectionUpdate(expected_revision=1), UUID(c["id"]))
    else:
        with pytest.raises(PermissionError):
            await other.connections()
        if user == 19:
            assert await other.profiles(catalog=True) == []
        else:
            with pytest.raises(PermissionError):
                await other.profiles(catalog=True)


@pytest.mark.asyncio
async def test_profile_versions_manual_model_and_forged_qualification(manager):
    c, p = await saved(manager)
    newer = await manager.save_profile(
        ProfileUpdate(
            expected_revision=1,
            name="New settings",
            model_id="another-exact-model",
            settings=ProfileSettings(),
        ),
        UUID(p["id"]),
    )
    assert newer["version"] == 2 and not newer["usable"]
    with pytest.raises(ManagementError, match="qualification_required"):
        await manager.set_profile_state(
            UUID(p["id"]), ProfileState(expected_revision=2, enabled=True)
        )
    with pytest.raises(ValidationError):
        ProfileCreate(
            name="Forge",
            connection_id=UUID(c["id"]),
            model_id="x",
            capabilities={"qualification": "live_worker"},
        )
    async with manager.sessions.begin() as session:
        versions = (
            await session.scalars(
                select(LlmModelProfileVersion)
                .where(LlmModelProfileVersion.profile_id == UUID(p["id"]))
                .order_by(LlmModelProfileVersion.version)
            )
        ).all()
        assert (
            len(versions) == 2
            and versions[0].snapshot["model_id"] != versions[1].snapshot["model_id"]
        )


@pytest.mark.asyncio
async def test_submission_is_document_free_atomic_and_requires_permit(manager):
    c, p = await saved(manager)
    payload = Submit(
        profile_id=UUID(p["id"]),
        expected_profile_revision=1,
        expected_connection_revision=1,
        acknowledge_cost=True,
    )
    with pytest.raises(ManagementError, match="authorization_required"):
        await manager.submit_test(UUID(c["id"]), payload)
    authorize_test(manager, c, p)
    result = await manager.submit_test(UUID(c["id"]), payload)
    async with manager.sessions.begin() as session:
        row = await session.get(LlmConnectionTest, UUID(result["id"]))
        assert row.delivery_state == "pending" and not row.result
        assert not {"document_id", "processing_run_id", "source"} & set(row.configuration)
        job = await session.get(Job, row.id)
        assert job.request_payload == {"llm_test_id": result["id"]}
        assert SENTINEL not in str(row.configuration) + str(row.ledger) + str(result)


@pytest.mark.asyncio
async def test_duplicate_claim_durable_budget_and_ambiguous_loss(manager):
    _, _, row = await submitted(manager)
    execution = Execution(manager, UUID(row["id"]))
    fence, config, ledger = await execution.claim()
    assert await execution.claim() is None
    first = ProbeBudget(execution, fence, config, ledger)
    for method, args in (
        (first.reserve, (100, 50)),
        (first.record, (None,)),
        (first.begin_repair, (uid(500),)),
        (first.observe_overrun, (10,)),
    ):
        with pytest.raises(ManagementError):
            method(*args)
    assert await first.before_attempt(100, 50) == 1
    second = ProbeBudget(execution, fence, config, ledger)
    assert await second.before_attempt(100, 50) == 2
    assert (await execution.check(fence)).reserved_tokens == 300
    manager.now = lambda: NOW + timedelta(seconds=91)
    assert await execution.claim() is None
    assert (await manager.get_test(UUID(row["connection_id"]), UUID(row["id"])))[
        "error_code"
    ] == "llm_test_ambiguous_attempt"


@pytest.mark.asyncio
async def test_test_job_and_delivery_roll_back_together(manager):
    c, p = await saved(manager)
    authorize_test(manager, c, p)

    def fail_insert(mapper, connection, target):
        raise RuntimeError("synthetic failure before request commit")

    event.listen(LlmConnectionTest, "before_insert", fail_insert)
    try:
        with pytest.raises(RuntimeError, match="synthetic failure"):
            await manager.submit_test(
                UUID(c["id"]),
                Submit(
                    profile_id=UUID(p["id"]),
                    expected_profile_revision=1,
                    expected_connection_revision=1,
                    acknowledge_cost=True,
                ),
            )
    finally:
        event.remove(LlmConnectionTest, "before_insert", fail_insert)
    async with manager.sessions.begin() as session:
        assert (
            await session.scalar(select(Job.id).where(Job.job_type == "LLM_CONNECTION_TEST"))
            is None
        )
        assert await session.scalar(select(LlmConnectionTest.id)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["replace", "rotate", "disable"])
async def test_credential_mutations_fence_existing_test(manager, action):
    c, _, row = await submitted(manager)
    execution = Execution(manager, UUID(row["id"]))
    fence, config, ledger = await execution.claim()
    await ProbeBudget(execution, fence, config, ledger).before_attempt(100, 50)
    change = CredentialChange(
        action=action, **({"secret": SecretStr(SENTINEL + "-new")} if action == "replace" else {})
    )
    await manager.credential(UUID(c["id"]), CredentialUpdate(expected_revision=1, change=change))
    with pytest.raises(ManagementError, match="configuration_stale"):
        await execution.check(fence)
    assert not any(p["usable"] for p in await manager.profiles())


@pytest.mark.asyncio
async def test_shared_allowance_cannot_be_refreshed_or_repaired(manager):
    _, _, row = await submitted(manager)
    execution = Execution(manager, UUID(row["id"]))
    fence, config, ledger = await execution.claim()
    await ProbeBudget(execution, fence, config, ledger).before_attempt(49000, 1000)
    fresh = ProbeBudget(execution, fence, config, ledger)
    with pytest.raises(ManagementError, match="budget_exhausted"):
        await fresh.before_attempt(1, 1)
    with pytest.raises(ManagementError, match="repair_unsupported"):
        await fresh.before_repair(uid(500))
    assert (await execution.check(fence)).reserved_tokens == 50000


@pytest.mark.asyncio
async def test_default_uniqueness_and_profile_stale_updates(manager):
    from sqlalchemy import update
    from sqlalchemy.exc import IntegrityError

    from app.models.llm import LlmModelProfile

    c, first = await saved(manager)
    second = await manager.save_profile(
        ProfileCreate(name="Second", connection_id=UUID(c["id"]), model_id="second-model")
    )
    # Database constraint only: no capability result is fabricated or enabled by an API.
    async with manager.sessions.begin() as session:
        await session.execute(
            update(LlmModelProfile)
            .where(LlmModelProfile.id == UUID(first["id"]))
            .values(enabled=True, is_default=True)
        )
    with pytest.raises(IntegrityError):
        async with manager.sessions.begin() as session:
            await session.execute(
                update(LlmModelProfile)
                .where(LlmModelProfile.id == UUID(second["id"]))
                .values(enabled=True, is_default=True)
            )
    with pytest.raises(ManagementError, match="qualification_required"):
        await manager.set_profile_state(
            UUID(first["id"]), ProfileState(expected_revision=1, enabled=True, is_default=True)
        )
    assert await manager.profiles(catalog=True) == []
    await manager.save_profile(
        ProfileUpdate(
            expected_revision=1,
            name="Changed",
            model_id="changed-model",
            settings=ProfileSettings(),
        ),
        UUID(second["id"]),
    )
    with pytest.raises(ManagementError, match="stale_revision"):
        await manager.save_profile(
            ProfileUpdate(
                expected_revision=1, name="Old", model_id="old-model", settings=ProfileSettings()
            ),
            UUID(second["id"]),
        )


@pytest.mark.asyncio
async def test_worker_sessions_are_task_owned_and_default_disabled(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from sqlalchemy import text
    from sqlalchemy.pool import NullPool

    from app.services.llm import test_worker

    engines = []

    def engine(url, **options):
        assert options["poolclass"] is NullPool
        result = create_async_engine(url, **options)
        engines.append(result)
        return result

    monkeypatch.setattr(test_worker, "create_async_engine", engine)
    settings = SimpleNamespace(
        llm_management_enabled=False,
        llm_connection_tests_enabled=False,
        sqlalchemy_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'task.db').as_posix()}",
    )

    async def operation(sessions):
        async with sessions.begin() as session:
            assert await session.scalar(text("SELECT 1")) == 1

    await test_worker.with_worker_sessions(settings, operation)
    assert engines == []
    settings.llm_management_enabled = settings.llm_connection_tests_enabled = True
    await test_worker.with_worker_sessions(settings, operation)
    await test_worker.with_worker_sessions(settings, operation)
    assert len(engines) == 2 and engines[0] is not engines[1]


@pytest.mark.asyncio
async def test_revocation_and_changed_settings_block_attempts(manager):
    c, p, row = await submitted(manager)
    execution = Execution(manager, UUID(row["id"]))
    fence, config, ledger = await execution.claim()
    await manager.save_connection(
        ConnectionUpdate(expected_revision=1, enabled=False), UUID(c["id"])
    )
    with pytest.raises(ManagementError, match="configuration_stale"):
        await ProbeBudget(execution, fence, config, ledger).before_attempt(100, 50)


@pytest.mark.asyncio
async def test_publisher_sends_id_only_and_duplicate_publication_is_bounded(manager):
    _, _, row = await submitted(manager)
    execution = Execution(manager, UUID(row["id"]))
    sent = []

    async def broker(task, args, identity):
        sent.append((task, args, identity))

    await publish_test(execution, broker)
    await publish_test(execution, broker)
    assert sent == [("wbs.test_agent_connection", (row["id"],), row["id"])]


@pytest.mark.asyncio
async def test_fake_worker_probes_never_enable_or_qualify_profile(manager):
    import re

    from llm_adapter_fixtures import SequenceBackend, reply, wire
    from llm_security_fixtures import FakeAuthorizer, FakeResolver

    from app.services.llm.registry import create_provider
    from app.services.llm.secure_transport import SecureJsonTransport

    statements = []

    @event.listens_for(manager.sessions.kw["bind"].sync_engine, "before_cursor_execute")
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    _, p, row = await submitted(manager)
    execution = Execution(manager, UUID(row["id"]))
    response = wire(reply("openai_compatible", {"schema_version": "1.0", "answer": "synthetic-ok"}))
    backend = SequenceBackend(response, response, response, response)

    def factory(config, budget, store, fence):
        return create_provider(
            SecureJsonTransport(
                manager.endpoints,
                FakeAuthorizer(),
                resolver=FakeResolver(),
                network_backend=backend,
            ),
            config.profile,
            manager.endpoints.pin(config.endpoint),
            budget,
            options=config.settings.options,
        )

    await execution.execute(factory, worker_identity="synthetic-worker")
    result = await manager.get_test(UUID(row["connection_id"]), UUID(row["id"]))
    assert result["state"] == "succeeded", result
    assert result["result"]["origin"] == "synthetic_fixture"
    assert result["calls_reserved"] == 4 and len(backend.calls) == 4
    assert all(item["qualification"] != "live_worker" for item in await manager.profiles())
    assert not any(
        re.search(r"\b(documents|document_chunks|document_processing_runs)\b", sql.lower())
        for sql in statements
    )


@pytest.mark.asyncio
async def test_missing_keys_preserve_metadata_but_replacement_is_unavailable(manager):
    from app.services.llm.errors import LlmSecurityError

    c, _ = await saved(manager)
    manager.keys = None
    preserved = await manager.save_connection(
        ConnectionUpdate(expected_revision=1, name="Metadata edit"), UUID(c["id"])
    )
    assert preserved["configured"] and preserved["revision"] == 2
    with pytest.raises(LlmSecurityError):
        await manager.credential(
            UUID(c["id"]),
            CredentialUpdate(
                expected_revision=2,
                change=CredentialChange(action="replace", secret=SecretStr(SENTINEL)),
            ),
        )
    async with manager.sessions.begin() as session:
        assert (await session.get(LlmConnection, UUID(c["id"]))).revision == 2
    assert await manager.profiles(catalog=True) == []


@pytest.mark.parametrize(
    "change", [{"secret": ""}, {"secret": None}, {"action": "preserve", "secret": "oops"}]
)
def test_empty_and_null_credentials_are_not_clear(change):
    with pytest.raises(ValidationError):
        CredentialChange.model_validate(change)


@pytest.mark.asyncio
async def test_permit_revocation_and_pending_test_limits(manager):
    c, p, row = await submitted(manager)
    with pytest.raises(ManagementError, match="already_pending"):
        await manager.submit_test(
            UUID(c["id"]),
            Submit(
                profile_id=UUID(p["id"]),
                expected_connection_revision=1,
                expected_profile_revision=1,
                acknowledge_cost=True,
            ),
        )
    execution = Execution(manager, UUID(row["id"]))
    fence, config, ledger = await execution.claim()
    manager.permits.clear()
    with pytest.raises(ManagementError, match="authorization_revoked"):
        await ProbeBudget(execution, fence, config, ledger).before_attempt(100, 50)


@pytest.mark.asyncio
async def test_completed_history_is_immutable_and_error_status_matches_job(manager):
    c, p, row = await submitted(manager)
    execution = Execution(manager, UUID(row["id"]))
    manager.now = lambda: NOW + timedelta(seconds=61)
    assert await execution.claim() is None
    async with manager.sessions.begin() as session:
        job = await session.get(Job, UUID(row["id"]))
        assert job.status == "FAILED"
    async with manager.sessions() as session:
        with pytest.raises(ValueError, match="immutable"):
            async with session.begin():
                record = await session.get(LlmConnectionTest, UUID(row["id"]))
                record.result = {"changed": True}


@pytest.mark.asyncio
async def test_migration_round_trip_preserves_legacy_and_refuses_test_history(tmp_path):
    from agent_schema_fixtures import migrate
    from sqlalchemy import text

    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'migrate.db').as_posix()}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: migrate(conn, target="d42a91c7e806"))
        async with sessions.begin() as session:
            await seed_legacy(session)
            await seed_agents(session)
        async with engine.begin() as connection:
            before = await connection.scalar(text("SELECT embedding FROM document_chunks"))
            await connection.run_sync(
                lambda conn: migrate(
                    conn, target="d42a91c7e806", start="b7e31d95a204", downgrade=True
                )
            )
            assert await connection.scalar(text("SELECT embedding FROM document_chunks")) == before
            assert (
                await connection.scalar(text("SELECT summary_text FROM document_summaries"))
                == "Preserved legacy text"
            )
            await connection.run_sync(
                lambda conn: migrate(conn, target="d42a91c7e806", start="b7e31d95a204")
            )
        endpoints, _ = endpoint()
        service = ModelManagement(
            sessions, access(), endpoints, keys(), tests_enabled=True, now=lambda: NOW
        )
        await submitted(service)
        async with engine.begin() as connection:
            with pytest.raises(RuntimeError, match="refusing downgrade"):
                await connection.run_sync(
                    lambda conn: migrate(
                        conn, target="d42a91c7e806", start="b7e31d95a204", downgrade=True
                    )
                )
    finally:
        await engine.dispose()
