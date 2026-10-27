"""Bounded section writer using existing adapters. No evidence tools or quality gate."""

import re
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.services.agents.contracts import (
    Fact,
    FindingStatus,
    SupportedClaim,
    TenderCategory,
    WriterFragmentContent,
)
from app.services.agents.evidence_types import EvidenceError, digest
from app.services.agents.nodes.writer_prompt import INSTRUCTIONS, PROMPT_VERSION
from app.services.agents.writer_render import finding_ids, source_attributes, validate_links
from app.services.agents.writer_types import (
    FragmentDraft,
    InclusionPage,
    WriterPolicy,
    WritingPartition,
)
from app.services.llm.base import BaseProvider
from app.services.llm.contracts import GenerationRequest, Message, Support, validate_result_binding
from app.services.llm.protocol_support import compact, parse_json, wire_input


class WriterFailure(EvidenceError):
    """Fixed metadata-only codes; never upstream bodies, source text or driver errors."""


def category_of(finding):
    return finding.category if isinstance(finding, Fact) else TenderCategory.OBLIGATIONS_CONDITIONS


def claim_identity(claim, binding, partition, role):
    return uuid5(
        NAMESPACE_URL,
        digest(
            {
                "version": "writer_claim.v1",
                "binding": binding,
                "partition": partition.index,
                "role": role,
                "claim": claim.model_dump(mode="json", exclude={"claim_id"}),
            }
        ),
    )


class SummaryWriter:
    def __init__(self, context_budget, guard, *, policy=None):
        self.budget, self.guard = context_budget, guard
        self.policy = policy or WriterPolicy()
        if context_budget.system_instructions != INSTRUCTIONS or context_budget.tool_schemas:
            raise WriterFailure("writer_context_mismatch")

    def payload(self, snapshot, partition):
        rows = snapshot.findings
        selected = [rows[i] for i in partition.finding_ids]
        refs = {e for row in selected for e in row.evidence_ids}
        return {
            "task": "write_bounded_section_fragment",
            "category": partition.category.value,
            "facts": [r.model_dump(mode="json") for r in selected if isinstance(r, Fact)],
            "requirements": [
                r.model_dump(mode="json") for r in selected if not isinstance(r, Fact)
            ],
            "evidence": [
                {
                    "evidence_id": str(i),
                    "exact_quote": snapshot.evidence[i].exact_quote,
                    "physical_pages": snapshot.evidence[i].physical_pages,
                }
                for i in sorted(refs)
            ],
            "gap": next(
                g.model_dump(mode="json")
                for g in snapshot.seal.gaps
                if g.category == partition.category
            ),
            "trust": "untrusted_register_data",
        }

    def request(self, provider, snapshot, partition):
        if (
            not isinstance(provider, BaseProvider)
            or provider.profile != self.budget.profile
            or snapshot.workflow.profile != self.budget.profile
        ):
            raise WriterFailure("writer_provider_mismatch")
        try:
            request = GenerationRequest(
                request_id=uuid4(),
                profile=provider.profile,
                messages=(
                    Message(role="system", content=INSTRUCTIONS),
                    Message(role="user", content=compact(self.payload(snapshot, partition))),
                ),
                response_schema="writer_fragment.v1",
                allowed_tools=(),
                output_mode="native_json_schema"
                if provider.profile.capabilities.json_schema == Support.SUPPORTED
                else "validated_json",
                input_token_budget=1,
                max_output_tokens=self.budget.output_tokens,
            )
            wires = [provider.encode(wire_input(request, repair)) for repair in (False, True)]
            tokens = max(max(len(compact(p).encode()) + 256, self.budget.count(p)) for p in wires)
            if not self.budget.fits(tokens):
                raise WriterFailure("writer_context_overflow")
            return GenerationRequest.model_validate(
                {**request.model_dump(), "input_token_budget": tokens}
            )
        except WriterFailure:
            raise
        except (ValueError, TypeError, KeyError):
            raise WriterFailure("writer_request_oversized_or_invalid") from None

    def partitions(self, snapshot, provider):
        """Map bounded register fragments to section drafts; final assembly is deterministic."""
        if (
            snapshot.workflow.profile != self.budget.profile
            or sum(len(p.model_dump_json().encode()) for p in snapshot.pages)
            > self.policy.max_register_bytes
        ):
            raise WriterFailure("writer_register_mismatch_or_oversized")
        result, findings = [], snapshot.findings
        for category in TenderCategory:
            ids = tuple(sorted(i for i, row in findings.items() if category_of(row) == category))

            def append(group, category=category):
                if not group:
                    return
                if len(result) >= min(
                    self.policy.max_fragments, snapshot.workflow.profile.max_calls
                ):
                    raise WriterFailure("writer_partition_limit")
                partition = WritingPartition(
                    index=len(result), category=category, finding_ids=group
                )
                try:
                    self.request(provider, snapshot, partition)
                except WriterFailure as error:
                    if str(error) not in {
                        "writer_context_overflow",
                        "writer_request_oversized_or_invalid",
                    }:
                        raise
                    if len(group) == 1:
                        raise WriterFailure("writer_entry_oversized") from None
                    middle = len(group) // 2
                    append(group[:middle])
                    append(group[middle:])
                    return
                result.append(partition)

            for start in range(0, len(ids), self.policy.fragment_entries):
                append(ids[start : start + self.policy.fragment_entries])
        return tuple(result)

    def binding(self, snapshot, partitions):
        return digest(
            {
                "workflow": snapshot.workflow.model_dump(mode="json"),
                "register": digest(snapshot.seal),
                "reading": digest(snapshot.reading),
                "partitions": [p.model_dump(mode="json") for p in partitions],
                "context": self.budget.sha256,
                "policy": self.policy.model_dump(mode="json"),
                "prompt_version": PROMPT_VERSION,
            }
        )

    def normalize(self, content, snapshot, partition, binding):
        allowed, included = set(partition.finding_ids), set()
        # Reserve protocol-level self-certification labels, not general document vocabulary
        # such as "approved vendor". This is not an entailment/quality verifier.
        self_certification = re.compile(
            r"\b(?:summary|draft|output)\s+(?:is\s+)?(?:fully\s+)?(?:approved|verified)\b"
            r"|\bconfidence(?:\s+score)?\s*[:=]?\s*\d+(?:\.\d+)?\s*%",
            re.I,
        )

        def claims(values, role):
            normalized = []
            for claim in values:
                validate_links(claim, snapshot, allowed)
                if self_certification.search(claim.text):
                    raise WriterFailure("writer_self_certification_denied")
                included.update(finding_ids(claim))
                data = claim.model_dump()
                data.update(
                    text=claim.text + "\n" + source_attributes(claim, snapshot),
                    fact_ids=tuple(sorted(claim.fact_ids)),
                    requirement_ids=tuple(sorted(claim.requirement_ids)),
                    evidence_ids=tuple(sorted(claim.evidence_ids)),
                )
                from app.services.agents.contracts import WriterClaim

                enriched = WriterClaim.model_validate(data)
                normalized.append(
                    SupportedClaim(
                        **enriched.model_dump(),
                        claim_id=claim_identity(enriched, binding, partition, role),
                    )
                )
            return tuple(normalized)

        prose, points = claims(content.claims, "section"), claims(content.key_points, "key_point")
        for omission in content.omitted:
            source = snapshot.findings.get(omission.finding_id)
            if source is not None and source.status not in {
                FindingStatus.SUPPORTED,
                FindingStatus.CONFLICTING,
            }:
                if omission.reason != "unresolved_source":
                    raise WriterFailure("writer_unresolved_omission_mismatch")
        inclusion = InclusionPage(
            binding=binding,
            stage="fragment",
            index=partition.index,
            available=partition.finding_ids,
            included=tuple(i for i in partition.finding_ids if i in included),
            omitted=tuple(sorted(content.omitted, key=lambda o: o.finding_id)),
        )
        return FragmentDraft(
            binding=binding,
            partition=partition,
            claims=prose,
            key_points=points,
            inclusion=inclusion,
        )

    async def write(self, provider, snapshot, partition, binding):
        await self.guard()
        request = self.request(provider, snapshot, partition)
        result = await provider.generate(request)
        await self.guard()
        try:
            validate_result_binding(request, result)
            if result.status != "completed":
                raise WriterFailure(
                    "writer_" + (result.failure.code.value if result.failure else "incomplete")
                )
            content = WriterFragmentContent.model_validate(parse_json(result.output_json))
            draft = self.normalize(content, snapshot, partition, binding)
        except EvidenceError:
            raise
        except (ValueError, TypeError, KeyError):
            raise WriterFailure("writer_output_invalid") from None
        await self.guard()
        return draft, result.usage
