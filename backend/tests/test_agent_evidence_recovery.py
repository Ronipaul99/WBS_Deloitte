"""Step 7 durable boundaries using disposable SQLite, not PostgreSQL qualification."""

import pytest
from agent_evidence_fixtures import canonical_source
from agent_orchestration_fixtures import delivery
from agent_orchestration_fixtures import execution as execution_fixture  # noqa: F401
from agent_schema_fixtures import access, scope, uid
from sqlalchemy import select

from app.models.agent_workflows import AgentStepRun
from app.services.agents.evidence import repository_for_workflow
from app.services.agents.evidence_storage import EvidenceArtifactStore
from app.services.agents.evidence_types import EvidenceArtifact, EvidenceError, ToolPolicy, digest
from app.services.agents.inventory import build_inventory
from app.services.agents.storage import FencedAttempt, WorkflowStore
from app.services.agents.tool_budget import WorkflowToolAllowance


@pytest.mark.asyncio
async def test_paged_storage_seal_replay_and_fencing(execution):
    store, clock = execution
    await canonical_source(store.sessions)
    repository = await repository_for_workflow(store)
    inventory = await build_inventory(repository)
    claim = await store.claim(await delivery(store), lease_seconds=30)
    artifacts = EvidenceArtifactStore(store, claim.fence)
    with pytest.raises(EvidenceError, match="not_sealed"):
        await artifacts.load_inventory()
    page = EvidenceArtifact(kind="inventory_page.v1", payload=inventory.pages[0])
    await artifacts.put(page, index=0, binding=digest(inventory.manifest.pin))
    # Interrupted after the first page: still no completed inventory.
    with pytest.raises(EvidenceError, match="not_sealed"):
        await EvidenceArtifactStore(store, claim.fence).load_inventory()
    await artifacts.save_inventory(inventory)
    await artifacts.save_inventory(inventory)
    assert await artifacts.load_inventory() == inventory
    from agent_schema_fixtures import migrate

    async with store.sessions.kw["bind"].begin() as connection:
        with pytest.raises(RuntimeError, match="refusing downgrade"):
            await connection.run_sync(
                lambda c: migrate(c, target="e53c7a19b402", start="c29f4b8e710a", downgrade=True)
            )
    async with store.sessions.begin() as session:
        rows = (
            await session.scalars(
                select(AgentStepRun).where(
                    AgentStepRun.workflow_run_id == store.scope.workflow_run_id
                )
            )
        ).all()
        assert len(rows) == len(inventory.pages) + 1
    changed = page.model_copy(
        update={"payload": page.payload.model_copy(update={"previous_sha256": "f" * 64})}
    )
    with pytest.raises(EvidenceError, match="replay_mismatch"):
        await artifacts.put(changed, index=0, binding=digest(inventory.manifest.pin))
    other = WorkflowStore(
        store.sessions, access(109, 101), scope(store.scope.workflow_run_id.int), now=clock
    )
    with pytest.raises(PermissionError):
        await EvidenceArtifactStore(other, claim.fence).load_inventory()
    clock.advance(31)
    with pytest.raises(FencedAttempt):
        await artifacts.save_inventory(inventory)


@pytest.mark.asyncio
async def test_tool_reservations_survive_reconstruction_cancel_and_lease_loss(execution):
    store, clock = execution
    claim = await store.claim(await delivery(store), lease_seconds=30)
    policy = ToolPolicy(max_calls=2)
    first = WorkflowToolAllowance(
        store, claim.fence, "a" * 64, policy, profile=claim.workflow.profile
    )
    await first.reserve("b" * 64)
    second = WorkflowToolAllowance(
        store, claim.fence, "a" * 64, policy, profile=claim.workflow.profile
    )
    usage = await second.reserve("c" * 64)
    assert usage.calls == 2 and usage.reserved_bytes == 2 * policy.response_bytes
    with pytest.raises(EvidenceError, match="budget_exhausted"):
        await first.reserve("d" * 64)
    assert (await store.check(claim.fence)).evidence_tools == usage
    await store.cancel()
    with pytest.raises(FencedAttempt):
        await second.reserve("e" * 64)


@pytest.mark.asyncio
async def test_inventory_rejects_foreign_descriptors_and_cancelled_reads(execution):
    store, _ = execution
    await canonical_source(store.sessions)
    repository = await repository_for_workflow(store)
    inventory = await build_inventory(repository)
    claim = await store.claim(await delivery(store))
    artifacts = EvidenceArtifactStore(store, claim.fence)
    first = inventory.pages[0]
    forged = first.model_copy(
        update={"entries": (first.entries[0].model_copy(update={"chunk_id": uid(999)}),)}
    )
    with pytest.raises(EvidenceError, match="chunk_mismatch"):
        await artifacts.put(
            EvidenceArtifact(kind="inventory_page.v1", payload=forged),
            index=0,
            binding=digest(inventory.manifest.pin),
        )
    await artifacts.save_inventory(inventory)
    await store.cancel()
    with pytest.raises(EvidenceError, match="workflow_unavailable"):
        await artifacts.load_inventory()
