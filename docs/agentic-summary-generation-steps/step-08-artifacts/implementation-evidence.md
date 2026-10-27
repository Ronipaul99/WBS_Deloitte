# Step 8 implementation evidence

Date: 2026-10-27. Status: **local implementation; external qualification pending**.
Step 8 is not fully complete. No actual analyst quality, PostgreSQL isolation,
worker recovery, live TLS or provider qualification is established by synthetic tests.

## Files and responsibilities

| Files | Responsibility |
| --- | --- |
| `backend/app/services/agents/nodes/analyst_prompt.py` | Versioned extraction-only instructions and untrusted-source boundary |
| `nodes/analyst.py` | Existing-adapter controller, actual wire-size admission, registered tool replay, canonical quote validation and trusted completion receipts |
| `nodes/analyst_nodes.py` | ANALYZE/CONSOLIDATE handlers, authorized history, bounded gap continuations, replay and explicit worker composition hook |
| `fact_register.py` | Source-anchored identities, aliases, conservative merging, section/document register pages, hash-chain validation and truthful missing-category states |
| `analyst_types.py` | Bounded extraction, receipt, gap, register-page and manifest artifacts |
| `contracts.py` | Analyst output extends existing FactBatch with untrusted quote proposals and explicit no-facts outcomes |
| `state.py` | Narrow nested artifact union, analyst checkpoint validation and CONSOLIDATE continuation edge |
| `budgeting.py` | Accept explicitly synthetic profiles for local contract/adapter verification without relabeling them live |
| `llm/contracts.py`, `llm/protocol_support.py` | Register `analyst.v1` on the existing provider interface/schema projection and extend its envelope cache |
| `backend/tests/analyst_fixtures.py`, `test_evidence_analyst*.py` | Synthetic adapter, extraction, pagination, gap, SQL recovery and opt-in PostgreSQL checks |
| Existing adapter fixture and contract schema snapshot | Supply explicit analyst no-facts fixtures and reflect the new response-schema identifier |

No new dependencies, migrations, routes, UI, worker services or schedulers were
added. Existing workflows, authentication, ingestion, vector storage and question
templates were not modified. The explicit composition hook returns two handlers;
it does not register or enable an application workflow.

## Extraction and controller

`analyst.v1` reuses Fact/Requirement validation. Models propose local claim/quote
UUIDs and Unicode code-point quote ranges. Trusted code accepts quotes only from
the assigned primary/context chunks or canonical chunks actually delivered by
successful registered tools. It re-reads canonical text and constructs Step 7
locators, keeping physical pages separate from printed labels and retaining
existing table/row precision limits. Provider-selected page/scope/hash fields
cannot enter this contract.

Empty results require `irrelevant_material` or `no_extractable_tender_facts`.
No-facts is a validated extraction outcome, not proof that the document lacks a
category. Refusal, truncation, invalid quotes, oversized requests, unsupported
normalization and exhausted budgets do not produce completion receipts.

Decimal normalization accepts only literal decimal representations, including
valid grouped thousands separators, with equal Decimal values. The original
numeric string must occur in supporting quotes. Magnitude/unit conversion is
rejected. These limited checks do not prove that a number, date or unit has been
semantically attributed correctly; independent verification remains Step 10.

Alternative tender options are separate conditioned facts. The prompt distinguishes
valid options from actual contradictions, preserves qualifiers/parties/deadlines,
and prohibits inferred dependencies. Dependencies must resolve to quoted
requirements within the same extraction. Unsupported cross-batch dependencies
remain a limitation, rather than guessed links.

The existing BaseProvider adapters perform all generation. Native tools and the
tested JSON-action envelope normalize to the same four Step 7 tools. No new
HTTP client, protocol, SDK, shell, SQL or URL execution tool exists. History is
bounded to four complete tool exchanges and at most three model-directed rounds
(default two). Overflow/repeated call IDs stop explicitly; old exchanges are not
silently dropped to fit context.

Request admission counts the actual encoded protocol, instructions, output schema,
tool definitions and replay wrappers, including possible format-repair overhead.
It reserves output plus Step 7 context headroom. Both the existing byte floor and
any supplied approved tokenizer count must fit. The estimate is not actual usage
or a claim about Llama capacity. The existing 8,000-character message bound can
block a batch even when its earlier plan fit; no text is silently trimmed.

All retries and format repair remain inside the existing adapter and its shared
budget. The controller does not retry failed generation, reset repair allowance
or switch models/providers. Reported usage is aggregated over tool rounds; an
unknown component keeps aggregate usage unknown. SQL admission/receipts remain
the Step 5 durable authority, including uncertain submitted requests.

## Identity and consolidation

`finding_identity.v1` binds the complete source scope, canonical quote text and
structured attributes. Model claim UUIDs, display numbering, array positions and
generated statement/obligation prose do not determine identity. NFC/whitespace
normalization is used for identity comparison, never to alter canonical evidence
or its offsets. REQ display codes are separate, derived from stable UUIDs.

Equivalent anchored findings merge only when their normalized claim text and
all structured attributes/conditions/dependencies agree. Every source link and
`(origin hash, proposed ID) -> stable ID` alias remains. Different units, quantities,
options, qualifiers and conflicting values remain distinct. Paraphrases with the
same identity that cannot be proven equivalent fail with an explicit identity
collision; there is no arbitrary winner or semantic deduplication claim.

Reduction is deterministic Python, not another whole-document model request.
It creates bounded section pages followed by bounded document pages, preserving
cross-section evidence links. Each page has at most 100 findings, 128 locators,
1,000 aliases and 200 KB. Pages form one ordered hash chain; a final manifest
binds root, count, inventory, configuration and input-set hash. Missing/reordered
pages and alias collisions fail validation. Individual oversized entries and
aggregate register overflow stop explicitly rather than discard references.

The policy defaults to 2,500 distinct findings and 4 MB of input extraction
artifacts, with hard ceilings of 5,000 findings and 8 MB. At most 120 reading
batches and three gap results enter reduction. Page results are checkpointed one
per continuation; no giant register is placed in one model request or checkpoint.

## Coverage, gaps and durable integration

Each ANALYZE completion contains its validated extraction and the matching Step 7
BatchCompletion in one nested `orchestration.v1` artifact. A failed attempt has no
processed receipt. Coverage is reconstructed from immutable completed batches
through Step 7 assigned/retrieved/delivered/processed transitions, rather than
writing independently committed coverage pages that could get ahead of results.
All batches must match the pinned ordered plan; blocked batches cannot be skipped.

The handlers reuse WorkflowStore completion, so extraction, receipt, checkpoint,
cursor and continuation commit atomically under the existing fence and lifecycle
checks. No transaction spans generation or retrieval. Reconstruction uses scoped
checkpoint APIs and validates current source, exact batch inputs, locators and
the workflow/profile/prompt/context/plan/policy binding. Completed batches are
not sent to providers again. Ambiguous paid attempts retain Step 5's conservative
recovery rule rather than being replayed with fresh allowance.

After reading, the controller uses the tender categories to select bounded
missing-category searches. Each gap continuation selects one still-unattempted
category in schema order, runs one scoped hybrid search, then allows the bounded
analyst follow-up tools. The default is one category round, maximum three.
Unattempted categories remain unknown; an empty bounded search does not prove
absence. Unavailable searches, exhausted allowances, incomplete reading,
conflicts, candidate-but-unverified facts and analyst-reported unresolved
categories remain explicit. Gap records and Step 7 tool reservations survive
reconstruction, including an unsuccessful search.

Coverage measures reading, not comprehension. Reading completion, extraction
success, locator validity, semantic support and human approval remain distinct.
The register is labeled not independently verified. No confidence percentage,
quality verdict, summary text or approval is generated.

## Scope and release boundary

See [persistence decision](persistence-decision.md), [test results](test-results.md),
[remaining inputs](remaining-inputs.md) and [scope review](scope-review.md).
Question-bank helpers were inspected for compatibility only; no mandatory
questionnaire, seed, re-embedding or question-driven coverage substitute was added.

The explicit factory uses the stored inventory, authorized workflow repository,
existing query embedder/reranker and durable tool allowance. The existing worker
runner must still supply the qualified BaseProvider with DurableCallBudget.
The two Step 8 handlers cannot form a complete WorkflowGraph; missing writer,
verifier and publication handlers still fail closed. No endpoint, runtime worker
registration, feature enablement or deployment was performed.
