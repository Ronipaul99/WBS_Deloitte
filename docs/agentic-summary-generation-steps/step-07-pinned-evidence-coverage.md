# Step 7: Implement pinned evidence access and document coverage

Status: independent local implementation present; required PostgreSQL, current-run
and deployed-worker qualification pending, 2026-10-27. Step 7 is not fully complete.
Feature defaults remain disabled. Depends on Steps 1-6.
See [implementation evidence](step-07-artifacts/implementation-evidence.md),
[test results](step-07-artifacts/test-results.md) and
[remaining inputs](step-07-artifacts/remaining-inputs.md).
Previous: [Step 6](step-06-model-management-ui.md).
Next: [Step 8](step-08-evidence-analyst.md).

## Objective

Give agents an immutable, scoped view of the ingested document and account for
every primary chunk, while retaining hybrid retrieval for targeted evidence.

## Implementation tasks

1. Add repository methods that accept a server-pinned completed processing-run ID,
   tenant/project/document scope, and bounded query/filter/pagination arguments.
   Existing `active_search_candidates` resolves current input per call and must
   not be used unchanged inside a long-running pinned workflow.
2. Validate that the pinned run belongs to the document, remains readable, and has
   completed source-linked chunks with the expected identity. Preserve RLS and
   explicit SQL scope predicates on sequential reads, neighbor reads, glossary
   access, and semantic/lexical searches. Do not hold document locks across inference.
3. Inventory ordered primary chunks, headings, physical pages, tables, glossary
   definitions and ingestion warnings. Snapshot/hash the inventory so retries use
   identical input and expose newly active input as stale rather than mixing runs.
4. Partition all primary chunks into ordered, bounded reading batches. Preserve
   heading and table context; overlapping references do not count as additional
   primary coverage. Record expected, processed, failed and unprocessed batch/chunk IDs.
5. Budget system instructions, tool schemas, source text and output together using
   the selected profile's tested context size. Use the server tokenizer when
   available; otherwise reserve conservative headroom and label estimates. Never
   silently truncate an oversized section, table, note register or model response.
6. Implement registered tools: `search_document`, `read_section`,
   `read_chunk_neighbors`, and `lookup_definition`. Inject scope from the run;
   reject model-supplied tenant/run overrides, unknown chunk IDs, out-of-scope
   filters, excessive result counts, and excessive repeated requests.
7. Build evidence references from canonical source text. Validate exact quote/range,
   hash, physical page and table metadata server-side. Distinguish printed page
   labels from physical page numbers. Retrieval scores are ranking signals only.
8. Treat source text as untrusted data. Tool results cannot register new tools,
   redirect credentials, issue SQL, or grant access. Revalidate lifecycle before
   new reads/calls and final publication, including retry/continuation paths.

## Proposed implementation targets

- Pinned-run methods in `app/services/ingestion/repository.py` and retrieval.
- `app/services/agents/evidence.py`, `inventory.py`, `tools.py`, and `budgeting.py`.
- Coverage and citation schemas; `test_agent_evidence.py` and PostgreSQL scope tests.

## Verification

Use multi-section/table/glossary fixtures, oversized sections, repeated headers,
Unicode text/ranges, empty sources and changed active runs. Prove every primary
chunk is assigned exactly once for coverage and can have additional context references.
Test cross-tenant/old-run ID attacks and document deletion between batches.
Verify that switching LLM profiles changes batching as needed but does not alter
stored embeddings or silently use another query embedding model.

For the private 110-page RFP, compare inventory/chunk hashes to the pinned source
run and keep extracted content in ignored artifacts. Coverage means text was
processed, not that every fact was correctly understood.

## Exit criteria

- [ ] Sequential coverage and targeted retrieval use the same pinned scope/run.
- [ ] No source is silently dropped to fit a token or run budget.
- [ ] Every evidence locator is derived/validated against canonical text.
- [ ] Partial/stale/deleting input is explicit and cannot become an approved full summary.
- [ ] Existing pgvector identity, dimensionality, and isolation guarantees remain intact.

Local assessment: pinned reads/search primitives, paged inventory, coverage,
budgeting, canonical locators and four read-only tools are implemented and tested.
Release checkboxes remain open because PostgreSQL RLS/vector/concurrency and
actual worker integration have not been verified. Historical local RFP data was
checked without using the configured database; the newer 391-chunk run still
needs a matching authorized canonical export. No Step 8+ node or summary route
was implemented or enabled.
