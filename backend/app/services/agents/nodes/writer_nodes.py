"""One fenced WRITE continuation per fragment, manifest page or intermediate draft."""

from app.services.agents.evidence_types import EvidenceError
from app.services.agents.nodes.writer import SummaryWriter, claim_identity
from app.services.agents.state import Node, NodeResult
from app.services.agents.writer_assembly import assemble_draft
from app.services.agents.writer_register import restore_writer_register
from app.services.agents.writer_render import source_attributes, validate_links
from app.services.agents.writer_types import WriterArtifact


class WriterNode:
    def __init__(self, writer, evidence, reading_plan):
        self.writer, self.evidence, self.plan = writer, evidence, reading_plan

    def handlers(self):
        # This does not fill missing VERIFY/REPAIR/PUBLISH or register a full graph.
        return {Node.WRITE: self.step}

    async def step(self, context):
        if context.cursor.node != Node.WRITE:
            raise EvidenceError("writer_node_mismatch")
        snapshot, artifacts = await restore_writer_register(
            context, self.evidence, self.plan, self.writer.guard, self.writer.policy
        )
        partitions = self.writer.partitions(snapshot, context.provider)
        binding = self.writer.binding(snapshot, partitions)
        fragments, inclusion = [], []
        for a in artifacts:
            if a.payload.binding != binding:
                raise EvidenceError("writer_replay_incompatible")
            if a.kind == "writer_fragment.v1":
                index = len(fragments)
                if (
                    inclusion
                    or index >= len(partitions)
                    or a.payload.partition != partitions[index]
                ):
                    raise EvidenceError("writer_fragment_replay_mismatch")
                for role, claims in (
                    ("section", a.payload.claims),
                    ("key_point", a.payload.key_points),
                ):
                    for claim in claims:
                        validate_links(claim, snapshot, partitions[index].finding_ids)
                        if claim.claim_id != claim_identity(
                            claim, binding, partitions[index], role
                        ) or not claim.text.endswith(source_attributes(claim, snapshot)):
                            raise EvidenceError("writer_claim_replay_mismatch")
                fragments.append(a.payload)
            elif a.kind == "writer_inclusion.v1":
                if len(fragments) != len(partitions):
                    raise EvidenceError("writer_fragment_missing")
                inclusion.append(a.payload)
            else:
                raise EvidenceError("writer_draft_already_sealed")
        if len(fragments) < len(partitions):
            result, usage = await self.writer.write(
                context.provider, snapshot, partitions[len(fragments)], binding
            )
            return NodeResult(
                next_node=Node.WRITE,
                artifact=WriterArtifact(kind="writer_fragment.v1", payload=result),
                usage=usage,
            )
        pages, draft = assemble_draft(snapshot, fragments, binding, self.writer.policy)
        if tuple(inclusion) != pages[: len(inclusion)] or len(inclusion) > len(pages):
            raise EvidenceError("writer_inclusion_replay_mismatch")
        await self.writer.guard()
        if len(inclusion) < len(pages):
            return NodeResult(
                next_node=Node.WRITE,
                artifact=WriterArtifact(kind="writer_inclusion.v1", payload=pages[len(inclusion)]),
            )
        await (
            self.evidence.publication_guard()
        )  # existing full source-integrity guard, not publication
        await self.writer.guard()
        return NodeResult(
            next_node=Node.VERIFY, artifact=WriterArtifact(kind="writer_draft.v1", payload=draft)
        )


async def build_writer_node(store, claim, reading_plan, context_budget, *, policy=None):
    """Explicit trusted hook; no runtime registration, model download or feature enablement."""
    from app.services.agents.evidence import EvidenceAccess, repository_for_workflow
    from app.services.agents.evidence_storage import EvidenceArtifactStore

    if context_budget.profile != claim.workflow.profile:
        raise EvidenceError("writer_profile_mismatch")
    await store.check(claim.fence)
    inventory = await EvidenceArtifactStore(store, claim.fence).load_inventory()
    evidence = EvidenceAccess(await repository_for_workflow(store), inventory)

    async def guard():
        await store.check(claim.fence)
        await evidence.guard()

    writer = SummaryWriter(context_budget, guard, policy=policy)
    return WriterNode(writer, evidence, reading_plan)
