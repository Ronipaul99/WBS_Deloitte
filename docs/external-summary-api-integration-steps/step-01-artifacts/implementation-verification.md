# Step 1 implementation and verification evidence

Date: 2026-10-28 (Asia/Calcutta).

Status: locally implemented through persisted acknowledgement; PostgreSQL and live/deployed qualification pending. This is not a complete or enabled summary integration.

## Baseline and scope

- Initial tracked checkout had no working-tree diff. The master plan and six-step documentation directory already existed as untracked files. They were preserved; their subsequent staging was not performed by this implementation.
- No applicable `AGENTS.md` was found in the repository scan.
- Read the index/master/Step 1, existing summary route, placeholder processor, permissions, settings, database helper, workflow/dispatch/worker conventions and destructive shared test setup.
- Initial migration head was `c92e6b4a710d`. New additive head is `d82f6a913b70`; verified from Alembic's script graph without loading application database configuration.
- Existing shared tests/conftest.py removes `.test-data`; it was not loaded. Tests use `--noconftest -p tests.upload_transaction_support`, temporary SQLite/storage and synthetic data.
- No application/Neon database, actual environment/secret file, live VM, private document or real summary endpoint was accessed for verification.

## Files and reasons

| Area | Change |
| --- | --- |
| `backend/app/core/config.py` | Default-disabled external gate, exact-origin configuration, excluded/non-repr SecretStr API key and bounded time/response settings. |
| `backend/app/schemas/external_summary.py` | Document-only submission, strict bounded acknowledgement and explicit external submission response with separate request/job identities. |
| `backend/app/models/external_summary.py` and model registration | Scoped durable request plus idempotency-key aliases; no generation Job or review-result model. |
| `backend/migrations/versions/d82f6a913b70_external_summary_submission_intents.py` | Add only coordination/key tables, scoped FKs, uniqueness/checks/index, PostgreSQL FORCE RLS and restricted separate-runtime-role grants. |
| `backend/app/services/external_summary_transport.py` | Fixed HTTPS submission, server headers/key, verified TLS, no redirects/environment proxies/compression, bounded acknowledgement and sanitized failures. |
| `backend/app/services/external_summary_submission.py` | Authorized source pinning, durable intent, key reuse, fenced worker submission, conservative ambiguity and identifier-only delivery/reconciliation. |
| `backend/app/api/routes/summaries.py` | External-only branch of existing POST/response union; legacy branch remains selected when disabled. |
| `backend/app/worker.py` | Task registrations and conditional entry in the existing Beat schedule. No new service/scheduler. |
| `backend/tests/test_external_summary_submission.py` | Production route/service/transport, migration and failure/compatibility checks with synthetic boundaries. |

No dependency changes were needed. Existing httpx, Pydantic, SQLAlchemy, Alembic and Celery are reused.

## Contracts and configuration

- Fixed approved origin is the supplied ngrok HTTPS host; configured origin must match it exactly. Changing host requires a reviewed code/policy change. The fixed path is `/api/v2.1/project-summary`.
- Payload contains only the server-authorized document UUID. No tenant-selected origin, credentials, model or processing-run parameter is sent.
- Only supplied acknowledgement status `RUNNING` is accepted; other wire statuses remain unqualified and fail closed. Job type must be exactly `DOCUMENT_SUMMERIZATION`.
- Acknowledgement validates UUIDs, strict integer bounds, aware/ordered timestamps, bounded step/error data and exact relative result path matching its job ID. Non-null upstream errors are not persisted as accepted acknowledgements.
- `result_url` is metadata only and never fetched. Oversized, compressed, malformed, wrong-document or secret-echoing responses cannot become accepted acknowledgements.
- `request_id` is the application intent. `job_id` remains null until acknowledgement. No acknowledged job is looked up or bound in Step 1; execution/readiness remains unavailable for later steps.
- Secret is excluded from Settings serialization/repr and configuration repr. Raw upstream/broker bodies/exceptions are not logged or stored. Errors expose fixed bounded codes only.

Settings declarations (placeholders/defaults; no actual files were provisioned):

```text
EXTERNAL_SUMMARY_ENABLED=false
EXTERNAL_SUMMARY_BASE_URL=<exact-approved-https-origin>
EXTERNAL_SUMMARY_API_KEY=<server-held-secret>
EXTERNAL_SUMMARY_CONNECT_TIMEOUT_SECONDS=5
EXTERNAL_SUMMARY_SUBMIT_TIMEOUT_SECONDS=20
EXTERNAL_SUMMARY_MAX_RESPONSE_BYTES=16384
```

Missing/invalid enabled configuration produces a sanitized submission configuration failure. Disabled configuration does not add a startup requirement. The API key is resolved for each newly claimed attempt; rotation does not change the pinned non-secret configuration fingerprint.

## Persistence and delivery boundaries

1. The existing POST checks tenant permissions, active project/document, workflow ownership, ready canonical run/release identity, current requester and summary revision.
2. The document lock serializes same-document intent creation; database uniqueness protects per-run requests and key identity. Every supplied alias is remembered in `summary_submission_keys` so an alias cannot later name different content.
3. The intent itself is the delivery record. Request creation/key association commit before broker publication. Publication failures retain pending intent for bounded reconciliation.
4. Existing Celery messages carry only tenant/request UUIDs. External execution never creates a local `DOCUMENT_SUMMARY` job or invokes/enqueues the placeholder processor.
5. The worker revalidates permissions, user auth version, lifecycle, source/configuration fingerprints and contract version before claiming. Its SUBMITTING lease commits before HTTP. No DB transaction spans the call.
6. Only the current non-expired fence can persist acknowledgement. Completed acknowledgement retains exact external ID and validated non-secret metadata, without changing workflow.summary_job_id or reading jobs.
7. Only proven connection-establishment/pool failures return to pending, with 30-second backoff and a five-attempt cap. Read/write/total timeouts, invalid responses, redirects and all HTTP rejections are conservatively unknown because upstream creation cannot be ruled out.
8. Cancellation/worker loss leaves SUBMITTING durable; expired ownership becomes SUBMISSION_UNKNOWN. Unknown attempts are not automatically reposted. No upstream idempotency support is assumed.

The request's run uniqueness is deliberately conservative across all states, including rejection/unknown/acknowledged. Regeneration, unknown-attempt resolution and multi-workflow association/verified binding are not silently implemented here.

Reconciliation publishes child identifiers without waiting for child tasks on a single-slot worker. It processes at most 100 eligible records per tenant per tick and refuses the global scan above 1,000 active tenants rather than silently starving a partial tenant subset. Broader operator partitioning is not implemented.

## Commands and actual results

Run from `backend`:

```text
.venv/Scripts/python.exe -m pytest --noconftest -p tests.upload_transaction_support tests/test_external_summary_submission.py tests/test_document_workflow_recovery.py tests/test_document_deduplication_api.py -q
```

Final result: **58 passed, 1 skipped**, 19.41 seconds, one existing Alembic configuration deprecation warning about `path_separator`. Skipped: PostgreSQL RLS/competing-claim verification, because no verified disposable PostgreSQL target and separate roles were provisioned.

Focused Ruff check on all changed backend sources, the new migration and tests: passed. Ruff format check on all new modules/migration/tests: passed; existing route/worker formatting was limited to the changed ranges. `python -m pip check`: no broken requirements. `git diff --check`: passed.

The migration test uses a new in-memory SQLite database, creates prerequisites there, upgrades/downgrades/re-upgrades the new migration, compares model/column shape and preserves a synthetic pre-existing tenant row. It never migrates the configured application database. It does not verify PostgreSQL grants/RLS or concurrent locking.

Earlier iterations exposed a test fixture argument collision and missing fake-broker isolation in a reconciliation test. That run was interrupted, the fixture was corrected and all subsequent runs stubbed broker publication. Its incomplete output is not included in the passing counts. There were no real summary-service calls.

## Covered behavior

- Exact method/origin/path/body/authentication headers; TLS/proxy/redirect options inspected through a fake client boundary.
- Wrong document/job/type/status, strict progress/attempt bounds, timestamp/path/step failures, malformed/oversized/compressed responses and sanitized transport/HTTP failures.
- Missing configuration, route permission denial/unknown roles, cross-scope IDs, incomplete/deleting sources, archived projects and authorization/source change before worker delivery.
- Reused intent, alias-key misuse across different documents, no local summary job/workflow binding, broker failure, repeated delivery, committed ownership before outbound I/O, cancellation, expired/replaced fences and conservative failure classification.
- Disabled external branch still returns the legacy summary JobResponse and invokes only its legacy dispatch boundary.
- Existing document workflow recovery and deduplication API regressions remain passing.

## Exit criteria and pending gates

Locally satisfied: typed bounded submission, backend-only secret boundary, fixed destination transport, durable scoped intent/key identity, short transaction ownership, existing-worker integration, fenced acknowledgement persistence, conservative ambiguity and disabled legacy compatibility.

Pending/unverified:

- Disposable PostgreSQL migration recovery, restricted-runtime grants, FORCE RLS, pooled scope and true competing-writer/locking behavior. SQLite sequential/fence tests are not concurrent PostgreSQL proof.
- Real TLS/ngrok reachability, actual request/body/status compatibility and deployed worker/Beat routing or uniqueness.
- Upstream idempotency/correlation, cancellation/retry contracts and other acknowledgement wire statuses. Unknown submissions remain blocked from automatic remote replay.
- Shared jobs row identity/ownership and full result contract: intentionally deferred to Step 2 and later.
- End-to-end summary progress/import/review: intentionally not implemented by this step.

No Steps 2-6 application functionality, frontend modifications, actual secret/environment changes, feature enablement, deployment, commits or pushes were performed. The new migration is a source artifact only; the live database was not upgraded.
