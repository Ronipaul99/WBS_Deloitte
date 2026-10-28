# Step 4: completed-result import evidence

Date: 2026-10-28. Locally implemented with synthetic fixtures; PostgreSQL, upstream and deployed-worker qualification remain pending. No integration enablement or application-database migration occurred.

## Baseline and boundaries

Initial status, staged/working diffs and file fingerprints were saved under ignored `backend/.data/external-summary-step04/`. Steps 1–3 already existed as uncommitted work. Concurrent staging and edits to the Step 4 instruction document were observed and preserved; this implementation did not stage, commit, reset or rewrite them. No AGENTS.md was found. The index, master plan, actual Step 4 document, predecessor artifacts, code, migrations and destructive shared conftest were inspected.

Storage gaps and the conservative contract decision were recorded in [design-boundaries.md](design-boundaries.md) before adding schema. The migration head at entry was e94b7d20a631. No verified disposable PostgreSQL target or local postgres/initdb/docker command was available. No application database, private PDF, VM, broker or upstream service was used for verification.

## Files changed and justification

| Backend file | Purpose |
| --- | --- |
| `app/schemas/external_summary_result.py` (new) | Versioned strict result, stored-draft, provenance and capability contracts. |
| `app/services/external_summary_import.py` (new) | Exact bounded payload admission, canonical validation, fenced local import, crash recovery and browser-independent reconciliation. |
| `app/models/external_summary.py` | Separate SummaryResultImport coordination and request document-scope uniqueness. Submission leases remain submission-only. |
| `app/models/domain.py` | Nullable scoped source-request marker and deferred structured JSON on the existing unique-per-document summary. |
| `app/models/__init__.py` | Register the new import model. |
| `migrations/versions/f05c8e31b742_external_summary_result_import.py` (new) | Add only Step 4 storage/constraints; FORCE RLS and restricted runtime grants; immutable committed-import identity trigger on PostgreSQL. Parent e94b7d20a631. |
| `app/core/config.py` | Bounded result byte limit and import visibility grace declarations; no enablement. |
| `app/services/external_summary_tracking.py` | Shared exact job predicates; observe import outcome/identity without result reads. |
| `app/services/external_summary_submission.py` | Internal trusted fingerprint-revision override for an already imported, source-matching summary, preventing the import's own revision advance from falsely invalidating its request. Current source/auth/config checks remain. |
| `app/schemas/external_summary_tracking.py` | Truthful IMPORTED state with matching summary ID/revision validation. |
| `app/api/routes/summaries.py` | Authorized bounded structured read branch; legacy mutation/approval safeguards and shared document locking. |
| `app/api/routes/generations.py` | Reject unsupported WBS use of a structured draft with no requirements register. No WBS algorithm changes. |
| `app/services/workflows.py` | A queued legacy summary attempt cannot overwrite an external draft. No external execution row is modified. |
| `app/worker.py` | One narrow import-reconciliation task on the existing Beat/worker infrastructure, conditional on the existing external gate. |
| `tests/test_external_summary_import.py` (new) | Contract, production route/service, durability, canonical-source, migration and isolation fixtures. |
| `tests/external_summary_schema_support.py` (new), existing Step 1/2 migration tests | Reconstruct the pre-Step-4 schema for historical migration tests and update head expectations. Historical migration files are untouched. |

## Result/schema policy

`external-summary-v1` accepts exactly the seven documented keys with unique IDs/orders and orders 1–7. Supported envelope is exactly `success`; answer statuses are `answered` and `insufficient_evidence`. These are explicit sample-based/synthetic contract policies, not live upstream qualification. Unsupported fields/categories/statuses are rejected.

Bounds: seven sections; 100 citations per section; 500 positive physical pages per page array; 20,000 characters per section/quote; 64 unique cited chunks per result. Section content exceeding its advertised edit limit is rejected. Confidence is null or a strict finite number in 0–100; booleans/strings are rejected and numeric representation is retained. Original content, null confidence, warnings, model/question-set/run IDs and citation metadata are preserved in the validated stored envelope. Schema UUID normalization is intentional; the accepted raw JSON digest separately identifies the external snapshot.

Default result admission is 1 MiB, configurable only within 1 KiB–2 MiB. A PostgreSQL octet_length/CASE expression checks stored JSON bytes before returning the payload; SQLite uses its byte-cast length equivalent. Application encoding and Pydantic validation apply after admission. Structured reads have the same bounded CASE admission with 2,048 bytes for the stored schema wrapper. The structured ORM column is deferred, preventing routine recovery/progress reads from loading it. Limits and SQL expressions have local/synthetic coverage; PostgreSQL execution is pending.

Citation policy: compare project/document/run to the trusted request; batch-read only exact tenant/project/document/run chunks, excluding embeddings. Validate canonical SHA-256 and exact Unicode substring quotes, including multiline text. Physical pages must equal the entire stored chunk page set (or the single canonical page column when a set is unavailable). Missing page metadata and narrower multipage attribution fail with explicit codes. No printed-page inference, whitespace/case normalization, semantic entailment, confidence percentage or human approval is claimed.

Legacy projection deterministically renders all ordered section titles/content with a 50,000-character ceiling. Overflow is rejected, never truncated. key_points and requirements are empty because no faithful register is supplied. Replacing an existing row requires the pinned revision, no approval and no existing requirements register. An approved/later-edited summary is never silently overwritten.

## Transactions, delivery and recovery

Submission identity and its ACKNOWLEDGED state remain unchanged. summary_result_imports stores a separate WAITING/VALIDATING/IMPORTED/INVALID/STALE lifecycle, first completion observation, due time, lease/fence, bounded crash attempts, sanitized error code and committed summary identity/digest/revision.

1. Reuse Step 2 metadata-only exact job verification and authorization. Completion requires COMPLETED or completed with progress 100; RUNNING at 100 is ineligible.
2. Claim under the document/workflow guard, request lock and import lock. Commit a fresh 120-second ownership lease before validation. Live ownership blocks competitors; stale ownership cannot accept results.
3. Read bounded exact payload and canonical chunks in a short scoped transaction; release it before continuation/test hooks. Capture raw result and canonical digests.
4. In a new short scoped acceptance transaction, recheck current authorization/auth version, active lifecycle/run/release identity/config, request/fence, job completion, stable result/canonical digests and expected summary revision.
5. Atomically write the unapproved structured/legacy summary, update compatible verified workflow associations, and commit the immutable imported identity. Historical generation associations are skipped; incompatible primary associations reject publication.

Repeated import returns the original summary identity without touching revision, content, edits or approval, including after a response is lost following commit. Later mutation of the external payload does not create another imported revision. The Jobs row is read-only throughout.

Missing/empty/null result data enters WAITING for a default 300-second grace, bounded to 1–900 seconds. Rechecks occur no sooner than 15 seconds and do not reset the first-observation clock. Expiry is explicit. Visibility waiting does not consume crash attempts; worker loss/expired leases are bounded to five claims. Database errors leave durable ownership for recovery and emit only a static sanitized diagnostic. Invalid/stale imports are terminal for automatic local reconciliation; generation is never resubmitted.

The existing worker's conditional Beat entry invokes a bounded reconciler (up to 1,000 tenants and 100 completed/due requests per tenant per tick). It uses database identifiers and processes imports directly, without child-task waits, browser dependence or network submissions. Terminal imports, not-yet-completed jobs, future due times and active leases are excluded. No new scheduler or worker service was added.

## Read/status handoff and deliberately unavailable UI

Authorized summary GET returns a structured branch with authoritative revision/approval, stored sections/document information, request/job/run/digest/imported-revision provenance and explicit unavailable structured-review/WBS capabilities. Legacy summaries retain their response and behavior. Corrupt stored structure/scope is rejected with a sanitized 409.

Status/recovery reads expose IMPORTED and matching persisted identity only after commit. They do not load jobs.result_payload or deferred structured content. Workflow storage receives the new summary identity/revision, but recovery deliberately remains on checkpoint rather than opening the incompatible legacy review renderer. Existing structured-summary PATCH/approve and WBS generation are rejected until the appropriate supported contracts exist.

The Step 3 frontend is unchanged and currently rejects IMPORTED metadata as unsupported, retaining last-known state with an unavailable read indication. Step 5 must implement its typed readiness/review handoff. Backend import success is therefore not browser review success, human approval or downstream WBS readiness.

## Verification commands and results

All backend tests used synthetic records and the isolated plugin, which does not read the application .env or delete backend/.test-data:

```text
.venv/Scripts/python.exe -m pytest --noconftest -p tests.upload_transaction_support tests/test_external_summary_import.py tests/test_external_summary_tracking.py tests/test_external_summary_submission.py tests/test_document_workflow_recovery.py tests/test_document_deduplication_api.py -q
```

The initial Step 4-only run passed 32 tests with one explicit PostgreSQL skip. A later expanded run had one migration-fixture failure (missing synthetic users.external_subject); that fixture was corrected, and focused migration recovery then passed. Subsequent combined verification passed 141 tests with three PostgreSQL skips before the final two scope/fork tests were added.

**Final backend run: 143 passed, 3 skipped, 3 warnings in 77.39 seconds.** The skips explicitly reserve Step 1, Step 2 and Step 4 PostgreSQL verification. Warnings are the existing Alembic path_separator deprecation. There were no failing tests in this final run. The Step 4 file contains 48 passing local tests and one explicit PostgreSQL skip.

Existing Step 3 browser regression command, from WBS_UI:

```text
node node_modules/@playwright/test/cli.js test --config ../backend/.data/external-summary-step03/playwright.config.mts external-summary-progress.spec.ts
```

**21 passed, 0 failed, 0 skipped in 34.7 seconds.** These are controlled browser/API mocks and preserve the existing pending/progress behavior; they do not establish a real imported-result browser review path. The two previously documented ingestion-navigation failures were not changed or represented as newly passing.

Checks include seven-section/null/Unicode/local-citation contracts, invalid envelopes/IDs/orders/limits/quotes/pages, foreign source/run/chunks, real scoped FK rejection in isolated SQLite, bounded payload admission, credential-echo rejection, unsupported completion combinations without result reads, visibility expiry, active/expired/replaced fences, duplicate imports, later edits/approval, cancellation-equivalent lifecycle changes, authorization removal, changed payload/canonical hashes, atomic fault injection at summary/workflow/marker and after commit, compatible forks/historical lineage, worker-only reconciliation, legacy worker protection, metadata-only progress, sanitized structured reads and migration upgrade/downgrade/re-upgrade preserving legacy summary/vector data.

Ruff check passed on all affected backend sources/migration/tests; Ruff format check passed on eight new/fully formatted modules; only changed ranges were formatted in larger legacy modules. pip check reported no broken requirements. No dependencies were added/upgraded. Working/staged whitespace checks passed. File-hash comparison against the initial baseline confirmed no frontend changes, historical migration changes or Step 1–3 artifact changes. Concurrent staging was preserved.

## Remaining qualification and exit status

Locally implemented: exact bounded result admission; structural/canonical validation; scoped structured persistence; fenced atomic one-time import; revision/approval protection; compatible association updates; browser-independent reconciliation; honest read/status/capability handoffs and legacy compatibility.

Pending: actual PostgreSQL JSON admission, FORCE RLS/grants, immutable-import trigger, pooling, competing importers and locking/recovery; live upstream status/envelope/normalization/page conventions and completion/payload timing; real worker/Beat deployment/routing. SQLite and synthetic tests do not establish these properties.

Existing privacy/retention tombstone hard-purge paths already encounter Step 1/2 request/run/workflow references; handling their complete retention/deletion ordering is not expanded here. Normal deletion/source invalidation prevents import and is tested. No retention policy or destructive cleanup was enabled.

The two previously reproduced baseline ingestion-navigation browser failures remain untouched. No seven-section editor, Step 5/6 implementation, real service calls, private uploads/downloads, environment/secret changes, feature enablement, VM/Docker/Nginx/CI changes, deployment, commits or pushes occurred. The additive migration is a source artifact only and was not applied to the application database.
