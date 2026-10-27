"""Paged evidence artifacts reuse existing scoped, immutable step records."""

from uuid import uuid4

from sqlalchemy import select

from app.models.agent_workflows import AgentStepRun
from app.models.domain import DocumentChunk
from app.services.agents.evidence_types import EvidenceArtifact, EvidenceError, digest
from app.services.agents.inventory import Inventory
from app.services.agents.repository import WorkflowRepository
from app.services.ingestion.pinned import PinnedEvidenceRepository


class EvidenceArtifactStore:
    def __init__(self, store, fence):
        self.store, self.fence = store, fence

    def query(self, kind):
        return select(AgentStepRun).where(
            AgentStepRun.tenant_id == self.store.access.tenant_id,
            AgentStepRun.workflow_run_id == self.store.scope.workflow_run_id,
            AgentStepRun.node == "evidence:" + kind,
            AgentStepRun.attempt == 1,
        )

    async def put(self, artifact, *, index, binding):
        artifact = EvidenceArtifact.model_validate(artifact)
        if type(index) is not int or not 0 <= index <= 100000:
            raise EvidenceError("evidence_artifact_cursor_invalid")
        payload = artifact.payload
        if hasattr(payload, "index") and payload.index != index:
            raise EvidenceError("evidence_artifact_cursor_mismatch")
        source = self.store.scope.source
        if hasattr(payload, "pin") and payload.pin.scope != source:
            raise EvidenceError("evidence_artifact_source_mismatch")
        key = digest(
            {
                "source": source.model_dump(mode="json"),
                "binding": binding,
                "kind": artifact.kind,
                "index": index,
            }
        )
        async with self.store.sessions.begin() as session:
            repo, run = await self.store._locked(session)
            self.store._fence(run, self.fence)
            await self.store._available(session, repo, run)
            pinned = PinnedEvidenceRepository(self.store.sessions, self.store.access, source)
            pin = await pinned._pin(session)
            if artifact.kind in {"inventory_manifest.v1", "inventory_page.v1"}:
                if binding != digest(pin):
                    raise EvidenceError("evidence_artifact_pin_mismatch")
                if artifact.kind == "inventory_page.v1":
                    if payload.pin_sha256 != digest(pin):
                        raise EvidenceError("evidence_artifact_pin_mismatch")
                    rows = (
                        await session.scalars(
                            select(DocumentChunk).where(
                                *pinned.predicates(),
                                DocumentChunk.id.in_([e.chunk_id for e in payload.entries]),
                            )
                        )
                    ).all()
                    descriptors = {r.id: pinned.canonical(pin, r).descriptor for r in rows}
                    if any(descriptors.get(e.chunk_id) != e for e in payload.entries):
                        raise EvidenceError("evidence_artifact_chunk_mismatch")
                elif payload.pin != pin:
                    raise EvidenceError("evidence_artifact_pin_mismatch")
            existing = await session.scalar(
                self.query(artifact.kind).where(AgentStepRun.batch == index)
            )
            if existing:
                if existing.input_sha256 != key or existing.artifact != artifact.model_dump(
                    mode="json"
                ):
                    raise EvidenceError("evidence_artifact_replay_mismatch")
            else:
                await repo.add(
                    AgentStepRun(
                        id=uuid4(),
                        tenant_id=run.tenant_id,
                        workflow_run_id=run.id,
                        node="evidence:" + artifact.kind,
                        batch=index,
                        attempt=1,
                        input_sha256=key,
                        state="completed",
                        artifact=artifact.model_dump(mode="json"),
                        usage={"source": "unknown", "input_tokens": None, "output_tokens": None},
                        completed_at=self.store.now(),
                    )
                )
                await session.flush()
            self.store._fence(run, self.fence)
            await self.store._available(session, repo, run)

    async def page(self, kind, *, after=-1, limit=32):
        if (
            kind
            not in {
                "inventory_manifest.v1",
                "inventory_page.v1",
                "reading_batch.v1",
                "coverage_page.v1",
            }
            or type(after) is not int
            or not -1 <= after <= 100000
            or type(limit) is not int
            or not 1 <= limit <= 64
        ):
            raise EvidenceError("evidence_artifact_cursor_invalid")
        async with self.store.sessions.begin() as session:
            repo = WorkflowRepository(session, self.store.access, self.store.scope)
            await repo._authorize()
            run = await repo._run()
            if run.requested_by != self.store.access.user_id or run.state in {
                "cancelled",
                "stale",
                "failed",
            }:
                raise EvidenceError("evidence_workflow_unavailable")
            await repo._current_source()
            rows = (
                await session.scalars(
                    self.query(kind)
                    .where(AgentStepRun.batch > after)
                    .order_by(AgentStepRun.batch)
                    .limit(limit)
                )
            ).all()
            return tuple(EvidenceArtifact.model_validate(r.artifact) for r in rows)

    async def save_inventory(self, inventory):
        if inventory.manifest.pin.scope != self.store.scope.source:
            raise EvidenceError("evidence_inventory_scope_mismatch")
        binding = digest(inventory.manifest.pin)
        for page in inventory.pages:
            await self.put(
                EvidenceArtifact(kind="inventory_page.v1", payload=page),
                index=page.index,
                binding=binding,
            )
        # The seal is written last. Partial pages never imply a completed inventory.
        await self.put(
            EvidenceArtifact(kind="inventory_manifest.v1", payload=inventory.manifest),
            index=0,
            binding=binding,
        )

    async def load_inventory(self):
        seal = await self.page("inventory_manifest.v1", limit=1)
        if not seal:
            raise EvidenceError("evidence_inventory_not_sealed")
        manifest, pages, after = seal[0].payload, [], -1
        while len(pages) < manifest.page_count:
            batch = await self.page("inventory_page.v1", after=after)
            if not batch:
                raise EvidenceError("evidence_inventory_pages_missing")
            pages.extend(a.payload for a in batch)
            after = pages[-1].index
        inventory = Inventory(manifest, tuple(pages))
        repository = PinnedEvidenceRepository(
            self.store.sessions, self.store.access, self.store.scope.source
        )
        await repository.guard(manifest.pin)
        return inventory
