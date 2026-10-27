# Contract decisions and legal transitions

## Ownership and versioning

All contracts carry `schema_version=1.0`. Workflow inputs require explicit workflow,
prompt and output-schema versions, requester, completed processing-state assertion,
tenant/project/document/run/source hash, and an immutable model-profile version.
Trusted application code must verify these assertions against authorized records.

`WorkflowInput`, `ModelProfileSnapshot`, `EvidenceReference`, `CoverageReport`,
`TenderSummary` and `VerificationReport` are server-owned artifacts. They are not
permission-granting model output or client request bodies. No routes accept them.

Model outputs use the smaller immutable `OUTPUT_CONTRACTS` registry:

| Schema ID | Contract | Role |
| --- | --- | --- |
| `facts.v1` | `FactBatch` | Analyst candidates, requirement IDs, unresolved categories |
| `summary_content.v1` | `SummaryContent` | Writer text and references to the supplied claim register |
| `verification.v1` | `VerificationContent` | Checked claims and findings |

These schemas forbid scope/profile/requester fields. The future controller binds
them to authorized workflow state and trusted evidence records. Tool arguments
also have no tenant/document/run fields. Provider adapters are interfaces only.
API protocol and exact model ID are separate fields; proprietary REST is rejected.

## Bounds and truthful outcomes

- Text: 8,000 code points; labels: 160; versions: 80; query: 1,000.
- Requests: 32 messages, 4 distinct allowed tools, qualified context/output budgets.
  Response JSON: 500,000 code points; at most 4 tool actions. Duplicate JSON keys,
  malformed JSON and nonstandard nonfinite constants are rejected. An object still
  requires validation against its requested output schema before use.
- Tools: search limit 20; neighbors 10 distinct chunk IDs/radius 0-2; cursor 0-100,000.
- Facts per batch: 100; requirements per batch: 100; final draft: 2,500 each;
  evidence: 5,000; evidence IDs per claim: 32; heading depth: 16.
- Reading inventory: 100,000 primary chunks, each in exactly one processed,
  unprocessed or failed partition. `complete` is derived and means reading coverage,
  not semantic accuracy. All 13 tender categories must appear once.
- Facts retain original values, exact decimal strings, units/currency, conditions,
  evidence, and distinct supported/unknown/conflicting/unsupported statuses.
  Conflicts require alternatives and evidence; unknown values cannot assert numbers.
- Drafts cannot claim human approval. Critical findings, incomplete coverage and
  explicit unsupported/conflicting critical facts block an acceptance verdict.
  Supported sections cannot promote unresolved claim references.
- Refusal/truncation/failure cannot carry a successful output. Usage is explicitly
  reported, estimated or unknown; unknown is not represented as zero.

These are conservative contract ceilings, not verified model/provider capacities.
JSON Schema snapshots describe field structure; Pydantic additionally enforces
cross-field invariants that plain JSON Schema validation alone cannot guarantee.
Provider-specific strict-schema transformations remain Step 4 work.

Evidence ranges are Unicode code-point `[char_start, char_end)`, with exact quote
length checked. Physical pages are positive, sorted, unique; table rows require a
table identity. The synthetic emoji test distinguishes code points from UTF-16.
Canonical chunk lookup, actual hash/page validation, scope authorization, and citation
entailment are intentionally not implemented in Step 1.

## Roles and legal transitions

| From | To | Actor |
| --- | --- | --- |
| pinned | reading | controller |
| reading | consolidating | analyst |
| consolidating | writing | controller |
| writing | verifying | writer |
| verifying | repairing | verifier; only with repair_pass=0 |
| repairing | verifying | writer; must record repair_pass=1 |
| verifying | human_review or quality_blocked | verifier |
| human_review | approved | human reviewer |
| any nonterminal | failed or cancelled | controller |

Approved, blocked, failed and cancelled are terminal. Analyst calls may repeat
within the reading stage; no graph loop is implemented here. After the first repair,
a second repair transition is invalid. A future controller must carry the trusted
consumed pass forward; callers cannot reset history by constructing a new assertion.
Human approval here is a transition contract, not a feature or permission check.

## Secret exclusion

Workflow/profile/tool/failure structures have no credential, endpoint, authorization,
header or arbitrary metadata fields; unknown fields fail validation recursively.
Collections are tuples and nested models are frozen/revalidated. Synthetic sentinel
tests cover rejection and sanitized validation diagnostics.

This is structural exclusion, not a general secret detector. Application code must
never put credentials into model names, prompt content or other free text. Do not
use Pydantic `model_construct`/unvalidated `model_copy(update=...)` for untrusted
payloads. Do not log raw validation inputs or upstream bodies: structured Pydantic
errors require `include_input=False` even with `hide_input_in_errors=True`.
Production connections, encryption, redaction and egress controls remain later work.
