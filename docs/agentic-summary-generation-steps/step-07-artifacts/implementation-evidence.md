# Step 7 implementation evidence

Date: 2026-10-27. Status: **independent local implementation; external qualification pending**.
Step 7 is not fully complete. Summary generation and live model features remain
disabled. No application database, cloud object store, generation provider or VM
was contacted or changed by this work.

## Files and responsibilities

| Files | Purpose |
| --- | --- |
| `backend/app/services/ingestion/pinned.py` | Explicit completed-run predicates, current authorization/RLS binding, lifecycle and identity checks, ordered/section/ID reads, glossary candidates and PostgreSQL vector/lexical candidates |
| `backend/app/services/agents/evidence_types.py` | Bounded pins, canonical descriptors, paged inventory/coverage, batches, completion receipts, tool allowances and evidence artifacts |
| `inventory.py` | Deterministic paged inventory, hash chain, manifest seal and replay validation |
| `budgeting.py` | Qualified-context planning, conservative/tokenizer accounting, complete primary partition, explicit context references and blocked-batch reasons |
| `coverage.py` | Assigned/retrieved/delivered/processed distinctions, validated completion binding, bounded reports and known source-loss warnings |
| `evidence.py` | Trusted workflow scope resolution, canonical quote/locator validation, pinned hybrid retrieval and publication-time inventory validation |
| `tools.py`, `tool_budget.py` | Four registered read-only tools, bounded untrusted outputs, repeated-request/global limits and fenced durable admission |
| `evidence_storage.py` | Immutable paged artifacts in existing scoped step records, idempotent writes, manifest-last sealing, authorized replay and fencing |
| `backend/app/services/agents/state.py` | Narrow typed artifact union and evidence-tool field in the existing execution ledger |
| `backend/app/models/agent_validation.py` | Allowlisted evidence step artifacts; preserve existing source scope and completed-record immutability |
| `backend/app/services/ingestion/retrieval.py` | Annotation-only repository import, allowing pure retrieval helpers to be reused without creating configured database sessions |
| `backend/migrations/versions/e53c7a19b402_add_pinned_evidence_artifacts.py` | Narrow step-artifact allowlist extension and monotonic evidence-tool accounting protection |
| `backend/tests/agent_evidence_fixtures.py`, `test_agent_evidence*.py` | Synthetic repository, batching, locator, tool, durable recovery and opt-in PostgreSQL verification |
| Existing migration-head tests | Expected application-head updates only, including the question-bank head assertion |

No new dependencies, routes, UI, worker services or agent handlers were added.
See [persistence gap](persistence-gap.md) for the migration justification.

## Scope and lifecycle

`repository_for_workflow` derives the source from the persisted authorized
tenant/run/requester workflow. Tool arguments contain no tenant, document,
processing-run or endpoint override. Every repository transaction rebinds trusted
tenant/user scope, checks active membership and both document-read and LLM-use
permissions, and uses explicit tenant/project/document/run SQL predicates.

The document must remain active, vectors visible, and its current completed run
must match the pinned source hash and processing identity. Counts/ordinal ranges
must match stored completed-run counts. Missing legacy processing identity or
source references fail closed. Changing the active input, source hash, processing
state, warnings or version identity does not repin an existing inventory.

All four read paths and both search streams use the same pin. The old
`active_search_candidates` behavior is unchanged and is not used for pinned
workflows. Current checks occur before/after short reads; embedding/reranking
runs outside database transactions. Tool allowance checks additionally retain
Step 5 cancellation, credential/profile availability, fencing and deadlines.
The later publication boundary has an explicit `publication_guard` which rereads
every descriptor and checks lifecycle, detecting changed uncited chunks too.
This guard is exposed, not wired into an unfinished summary/publication flow.

## Inventory and immutable storage

Descriptors retain ordered chunk identity, original stored chunk hash, independent
UTF-8 text hash, full source-metadata hash, heading/section identity, physical
pages, source references with primary/overlap/header roles, table/row references,
printed labels when present and warnings. Unknown labels/coordinates remain
unknown. The inventory contains descriptors, not raw document text or embeddings.
Glossary candidates remain source-linked chunks, not fabricated definitions.

The original ingestion hash includes tokenizer/extractor provenance. Step 7 does
not mislabel SHA256(text) as that hash or claim to reproduce an original chunker
digest without its complete original inputs. Independent text/metadata hashes
bind replay to the canonical records actually read.

Inventory pages contain at most 64 descriptors and 250 KB. Each page binds its
pin/index/previous-page hash. A compact versioned manifest binds the final root,
page count and primary chunk count; it does not require a giant hash list in one
checkpoint. Restore validates page order, chain, count, ordinals and uniqueness.

Evidence pages reuse `AgentStepRun` with reserved `evidence:<kind>` node identities.
They are not synthetic graph completions and do not advance the graph cursor.
Writes lock/recheck the existing workflow fence and lifecycle, validate inventory
entries against the current scoped canonical rows and compare replay identities.
Completed records remain immutable. The manifest is written last, so a crash
after any partial page cannot make an inventory available as complete. Reads
recheck requester authorization, source and the seal/chain. Fresh coverage
snapshots must use new sequence identities; completed pages are not overwritten.

## Batches, token accounting and coverage

Every primary chunk appears exactly once in the ordered batch plan. Heading
boundaries are retained; canonical table/header context remains in the text and
its source-reference roles. Additional chunk context must be explicitly attached,
scoped, verified and budgeted; it never increases primary coverage. Primary and
context IDs cannot overlap inside a batch.

Planning counts instructions, tool schemas, serialized source/context wrappers
and reserved output together. Qualified context/output limits are required.
An injected approved local tokenizer has a pinned identity; otherwise the policy
counts UTF-8 bytes as a conservative estimate and labels it accordingly. At least
512 tokens or 10% context headroom is reserved for protocol overhead. This is not
a claim about actual tokenizer usage or guaranteed support for arbitrary models.

Oversized canonical chunks are not silently split or truncated. This version
returns a blocked batch (`oversized_context`) when exact chunk-level processing
cannot fit. Run call/token planning exhaustion is `run_budget_exhausted`. All
primary IDs remain accounted for, including blocked batches. Actual paid-call
admission remains Step 5's responsibility; planning estimates reserve no provider
request and make no billing/usage assertion.

Coverage distinguishes assigned, retrieved, delivered, processed, failed and
blocked states. Processed requires the correct pinned batch/inventory/primary
IDs plus a trusted controller receipt referencing a validated completed artifact.
Only the future trusted node/controller may issue that receipt; model/tool output
cannot issue it. Tool reads never change processed coverage. Empty sources fail
as blocked rather than report a vacuous complete result. Known partial/unsupported
element-loss warnings prevent a full coverage label even after available chunks
are processed. Coverage measures reading, not comprehension or factual accuracy.

## Tools, retrieval and citations

`search_document`, `read_section`, `read_chunk_neighbors` and `lookup_definition`
consume the existing validated ToolAction contracts. Unknown tools, extra scope
arguments, foreign IDs, invalid/foreign section cursors, unsafe/excessive bounds
and repeated requests are rejected. Section results carry a continuation cursor;
glossary results expose remaining candidates and never prove absence. Oversized
results return a bounded error instead of silently removing evidence.

Production tool admission commits before each operation into the existing
execution ledger. Its binding includes inventory and context/profile identity.
Policy, request hashes/counts, calls and reserved output bytes/tokens survive
reconstruction and cancellation/retry. Failed/ambiguous operations do not refund
allowances. A new object or call ID does not reset the budget. The additive
PostgreSQL trigger prohibits decreases or binding/policy/request-count resets.
These are tool-I/O allowances; later model calls must still use Step 5 durable
request/token accounting for the complete assembled request.

Search reuses lexical term normalization, glossary aliases and reciprocal-rank
fusion. PostgreSQL executes pinned vector and lexical candidates; SQLite search
fails closed. The injected existing query embedder must exactly match the pinned
provider/model/revision/dimensions/formatting identity. Optional loaded rerankers
may be reused without downloading/loading a second model. Generation-profile
changes affect planning, not stored BGE vectors. Scores rank unverified evidence.

Citations use exact half-open Unicode code-point ranges in canonical chunk text.
Quotes, stored hash, text/metadata identities, source scope, pages and headings
are checked server-side. Physical pages and printed labels are distinct. A row
locator is omitted when context/overlap spans multiple rows; no character-to-row
or cell coordinate map is invented. Missing pages or locator fields outside the
existing evidence contract produce an explicit error, never truncated metadata.

Source instructions remain untrusted strings. They cannot select another scope,
register tools, run commands/SQL, load files, redirect credentials or call an LLM.
Tool errors contain fixed codes, not raw provider/driver/source exceptions.

## Compatibility and qualification

The migration is additive from initial head `c29f4b8e710a`; older migrations,
ingestion/vector schemas, RLS relationships and question-bank data are unchanged.
It widens only the existing step-artifact allowlist and guards a new typed JSON
accounting field. Downgrade refuses evidence artifacts/accounting rather than
discarding history. Checkpoints keep the application-owned Step 5 design.

The annotation-only import change in retrieval has no search behavior change;
an isolated import check confirms evidence access does not create configured
database sessions. No model-management/credential/endpoint code was changed.

See [verification results](test-results.md), [remaining inputs](remaining-inputs.md)
and [scope review](scope-review.md). Local/SQLite success does not establish
PostgreSQL RLS, real vector-query semantics/performance or deployed-worker safety.
