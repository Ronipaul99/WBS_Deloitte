# Step 9: Implement structured tender summary writing

Status: planned. Depends on Steps 7-8.
Previous: [Step 8](step-08-evidence-analyst.md).
Next: [Step 10](step-10-verification-repair.md).

## Objective

Turn the fact/requirement register into a readable, structured summary without
inventing facts or discarding the source relationships needed by future WBS agents.

## Output contract

The versioned `TenderSummary` contains these bounded sections:

| Section | Expected information |
| --- | --- |
| Executive overview and parties | What is being procured, issuer and stated parties |
| Scope and deliverables | Capacity, locations, units, inclusions and exclusions |
| Eligibility | Technical/financial criteria and qualifying branches |
| Technical requirements | Obligations, standards when stated, performance/acceptance criteria |
| Dates and milestones | Submission/validity/completion dates and qualifying conditions |
| Commercial and financial terms | Currency, amounts, payment terms and contract/PPA duration |
| Securities | EMD/PBG values, options, exemptions and applicable conditions |
| Submission/evaluation/award | Proposal contents, evaluation and award rules |
| Requirements register | Stable IDs, obligations, deliverables and evidence |
| Risks/conflicts/open questions | Supported issues, alternative values and unresolved information |

Each factual claim points to fact/evidence IDs from the register. Executive prose
is not exempt from source support. Separate extracted obligations from proposed
future work or assumptions; WBS decomposition is not generated in this step.

## Implementation tasks

1. Implement a writer node/prompt that accepts the pinned register and selected
   model-profile snapshot, not an unbounded conversation or the entire raw PDF.
2. Generate bounded section drafts and assemble them deterministically. For long
   registers, use hierarchical section writing and maintain a manifest of facts
   available/included/omitted. Do not silently truncate to a model context window.
3. Preserve stable requirement IDs, alternative tender options, original units,
   conditions and exact evidence IDs. Do not infer responsibility, dependencies,
   durations, totals or deadlines when the source does not state them.
4. Render unresolved categories explicitly as not found/unresolved/conflicting.
   A search miss alone is not proof of absence; carry the coverage/gap findings.
5. Validate the provider output schema and bounded fields. Use the shared single
   format-repair policy for malformed JSON; refusal/truncation remains explicit.
6. Construct the legacy `summary_text`, `key_points` and `requirements` projection
   deterministically from the structured draft. Do not maintain independently
   generated outputs that can disagree. Attach provenance and coverage metadata.
7. Checkpoint the draft as an intermediate artifact. Only Step 10 can issue the
   quality decision that allows Step 11 to publish it for human review.

## Proposed implementation targets

- `backend/app/services/agents/nodes/writer.py`, prompt assets and summary schemas.
- A deterministic compatibility renderer and `test_summary_writer.py`.

## Verification

Test unknown fields, contradictions, long registers, empty sections, multiple
EMD options, currency/unit preservation, reordered requirements, and unsupported
invented evidence IDs. Assert executive prose is also linked to support. Check
legacy and structured projections agree. A fixture with missing dates must not
produce plausible fabricated dates or describe unknown facts as verified.

## Exit criteria

- [ ] Output is readable, bounded, typed and based on the fact register.
- [ ] Every factual claim retains evidence relationships and critical qualifiers.
- [ ] Unknown/partial/conflicting information is explicit.
- [ ] No output is approved or labelled verified by the writer alone.
- [ ] Changing provider does not change the output schema or requirement-ID contract.
