# Step 2 schema and permission decisions

## Scope and storage

There are 11 new protected tables. All contain `tenant_id`; workflow tables also
bind `workflow_run_id` to a scoped parent. Composite foreign keys bind documents,
processing runs, jobs, connections, profiles/versions, revisions, chunks and approval
reviewers. A matching tenant alone is insufficient to link evidence to another
document, processing run, revision or workflow. Requesters/reviewers must have a
membership in the recorded tenant.

| Records | Data / mutability |
| --- | --- |
| `llm_connections` | Provider/protocol, bounded endpoint policy metadata, enabled flag, same-connection active credential; provider/protocol and scope immutable |
| `llm_credential_versions` | Version, bounded ciphertext/nonce bytes, key version, created/retired metadata; no plaintext column; only retirement metadata mutable |
| `llm_model_profiles` | Same-connection active version, enabled/default state; one default per tenant |
| `llm_model_profile_versions` | Immutable validated `ModelProfileSnapshot` and version; provider/protocol must match connection |
| `agent_workflow_runs` | Immutable pinned `WorkflowInput`, source hash, profile version, requester and budget; state/lease/fencing metadata stored but not processed |
| `agent_step_runs` | Unique run/node/batch/attempt, input hash, typed artifact, completion, explicit usage; completed records cannot be rewritten |
| `agent_checkpoints` | Append-only unique run/sequence, node, input hash and typed JSON artifact; no pickle/generic transcript/production saver |
| `workflow_dispatch_outbox` | Unique run/task/continuation, exact run/job binding, delivery/lease/retry timestamps; no dispatcher or lease-processing code |
| `summary_revisions` | Immutable versioned `TenderSummary`, provenance and explicit quality outcome; separate from approval |
| `summary_evidence` | Immutable revision/claim/evidence/chunk linkage, canonical hash, typed locator and exact quote span |
| `summary_approval_events` | Append-only exact revision, reviewer, decision/time and expected version; one event per summary/expected version |

JSON is bounded both by typed validation and database size checks. PostgreSQL adds
object/recursive forbidden-field/UTF-8 byte checks. Policy metadata is limited to
8 KiB, profile snapshots to 16 KiB, workflow input to 32 KiB, budgets to 4 KiB,
step/checkpoint artifacts to 1 MiB, usage to 2 KiB, locators to 64 KiB, and revisions
to 8 MiB. Typed artifacts are limited to Step 1 fact/writer/verification schemas.
No new code writes prompt transcripts or credentials into existing generic job payloads.

Forbidden-field checks are structural, not a detector for secrets hidden in free
text. Application code must not insert keys into model names or source content.
No encryption or provider credential management is implemented in this step.

## Legacy compatibility and revision rules

The unique-per-document `DocumentSummary` remains. Its legacy text, key points,
requirements and approval flag are preserved during migration, with
`content_origin=legacy_unverified`, null active revision and zero revision counters.
There is no backfill of generated/verified revisions or approvals.

New pointers use `(revision, tenant, document, summary)` composite scope. A repository
compare-and-swap checks the expected version, latest request sequence and current
non-deleting completed source. Pointer updates reset approval and advance the version.
Generated text is immutable in the revision; legacy fields are a compatibility
projection. PostgreSQL rejects editing a live agent projection without a new
revision or an explicitly cleared pointer. Clearing a pointer invalidates approval.

Approval events target the exact active revision and expected version. An insert
performs a guarded version increment and updates only approval projection metadata.
Blocked/partial/stale content cannot be approved. An old event cannot confer approval
on another revision. Concurrent/stale pointer or audit writes fail. The PostgreSQL
trigger path has been written but awaits actual integration execution.

Existing summary routes were not rewired. The existing summary table retains its
legacy access model; new scoped reads add explicit predicates, new parent FKs prevent
cross-tenant attachment, and pointer triggers protect new agent metadata. RLS is
installed on all **new** protected tables. Retrofitting unrelated legacy tables or
implementing approval/review routes is outside this step.

## Job-state projection

| Workflow state | Existing job status | Human approval |
| --- | --- | --- |
| queued | QUEUED | None |
| running | IN_PROGRESS | None |
| review_required | COMPLETED | Generation completed; still a draft |
| partial / quality_blocked / stale / failed | FAILED | Never implies accepted output |
| cancelled | CANCELLED | None |

There is no `approved` workflow/job state. Approval belongs to revision-specific
audit history. This is a pure mapping; no transition executor, retry loop or graph
was added. Lease/fencing/sequence processing belongs to Step 5.

## Permissions and transaction boundary

| Permission | Admin | Editor | Viewer / unknown role |
| --- | --- | --- | --- |
| `llm:manage` | Yes | No | No |
| `llm:use` | Yes, with summary:update | Yes, with summary:update | No |
| `llm:usage_audit` | Yes | No | No |

Repositories require an explicit caller-owned transaction, authenticated
`StorageAccess`, active user/tenant membership and current role permission. They
apply tenant/resource predicates even on SQLite. Workflow repositories additionally
bind the full source scope and workflow ID; a checkpoint ID alone is insufficient.
Credential reads are manager-only and return ciphertext to backend callers, not a
browser DTO. Usage auditing projects identifiers/stage/usage rather than artifacts.

PostgreSQL uses transaction-local `app.tenant_id`, `app.agent_workflow_run_id` and
`app.agent_user_id`, rebound for each operation. Policies fail closed without tenant
context; workflow records additionally require the selected run. These settings
are trusted application context, not independent authentication. End users must
never receive a database connection or choose authorization scope through model output.

Migration verifies distinct owner/runtime roles, no runtime superuser/BYPASSRLS,
no inherited migration role, and no runtime schema CREATE privilege. It enables and
forces RLS, removes PUBLIC table privileges, and limits runtime mutation privileges
on append-only records. An explicit owner policy permits migration safety inspection
under FORCE RLS; runtime must not inherit it. No SECURITY DEFINER bypass is used.
References: [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
and [trigger functions](https://www.postgresql.org/docs/current/plpgsql-trigger.html).

## Deletion order and downgrade

No new retention/deletion executor is added. Referential restrictions intentionally
prevent dropping pinned source/vector records while summary provenance still refers
to them. Existing vector dimensions, ingestion outbox constraints and existing
ingestion cascade rules remain unchanged.

Future authorized maintenance must stop/fence work, clear summary pointers, then
remove approval events, evidence, revisions, workflow outbox/checkpoints/steps and
runs before deleting their jobs/source data. Remove legacy summary rows before
their documents. Clear profile active-version and connection active-credential
pointers before deleting their referenced versions; delete dependent workflows
before profile versions, then profiles, credential versions and connections.
Runtime cannot directly delete append-only records; a separately authorized
privileged cleanup path must be designed in the lifecycle step.

Downgrade refuses any new records or populated summary agent metadata. Empty
disposable up/down/up tests preserve historical data. A populated deployment needs
a reviewed forward fix, not a routine downgrade. PostgreSQL execution remains pending.
