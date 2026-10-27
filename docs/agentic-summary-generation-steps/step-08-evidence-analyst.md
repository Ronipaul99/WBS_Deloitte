# Step 8: Implement the evidence analyst and fact register

Status: local implementation verified by synthetic tests; external qualification
pending. Depends on Steps 4-7. Step 8 is not fully complete.
Previous: [Step 7](step-07-pinned-evidence-coverage.md).
Next: [Step 9](step-09-summary-writer.md).

Implementation evidence: [Step 8 artifacts](step-08-artifacts/implementation-evidence.md).
See [test results](step-08-artifacts/test-results.md) and
[remaining inputs](step-08-artifacts/remaining-inputs.md). Local tests do not qualify
PostgreSQL, deployed workers, real providers or analyst quality. Summary generation
remains disabled; writer/verifier/publication/API integration is not implemented here.

## Objective

Extract a reusable register of supported tender facts and requirements from all
reading batches, with bounded agent-directed follow-up searches for gaps.

## Implementation tasks

1. Implement the evidence analyst node with versioned role instructions and a typed
   result/action schema. Give it only the registered Step 7 tools and its assigned
   batch/context. Document instructions remain evidence, not system instructions.
2. Extract statements, original/normalized values, currency/units, conditions,
   parties, deadlines, obligations, deliverables and supporting quote IDs. Preserve
   alternatives such as EMD options and conditions attached to financial requirements.
3. Allow either native tool actions or the tested JSON action envelope from Step 4.
   Validate actions before execution; the controller owns maximum tool rounds,
   tool results, total calls/tokens and legal transition state.
4. Process every inventory batch and checkpoint each validated result. Emit an
   explicit no-facts result for irrelevant material; never skip a failed batch
   while incrementing it as processed. Retry only according to the shared policy.
5. Consolidate findings hierarchically into bounded section registers and then a
   document register. Define stable IDs independent of list order and model prose;
   keep human-friendly REQ codes as separate display values. Record aliases when
   deduplicating equivalent requirements rather than losing their source links.
6. Merge truly equivalent facts while retaining multiple evidence references.
   Distinct units, quantities, eligibility branches, tender options, and contradicting
   dates remain distinct qualified entries. Preserve source qualifiers and uncertainty.
7. Build a missing-category checklist from the tender schema. The analyst may
   request focused hybrid/glossary/neighbor evidence for gaps. Bound the search
   rounds and preserve unfilled/contradictory findings after the budget is spent.
8. Record non-overlapping coverage separately from extraction outcomes, evidence
   validity and semantic support. A found chunk is a candidate, not a verified fact.
   Do not assign a model-generated percentage to confidence.

## Proposed implementation targets

- `backend/app/services/agents/nodes/analyst.py`, `fact_register.py`, and prompt assets.
- Typed requirement/fact/action schemas and graph transitions.
- `test_evidence_analyst.py`, fixtures for tables/conditions and bounded tool actions.

## Verification

Test repeated facts, table rows across pages, alternative EMD values, total versus
per-unit capacity, glossary definitions, missing issuer, unknown dates, contradictory
clauses, reordered requirements and JSON-action malformed/repeated loops. Source
text that says to call another URL, leak keys, or ignore scope must not execute.
Test reducer overflow/truncation and replay of completed batches.

Run the same fixture extraction with fake OpenAI/native-tool and compatible/JSON
action providers. Actual live quality belongs in Step 14, not a fixture's canned success.

## Exit criteria

- [ ] Every processed source batch has a validated extraction outcome.
- [ ] Consolidated facts retain qualifications, conflicts and traceable evidence.
- [ ] Requirement identity survives ordering/deduplication without citation drift.
- [ ] Missing categories trigger only bounded scoped searches and remain truthful if unresolved.
- [ ] The node can resume without silently repeating completed extraction work.
