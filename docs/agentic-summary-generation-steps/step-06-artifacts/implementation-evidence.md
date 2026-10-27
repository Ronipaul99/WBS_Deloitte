# Step 6 implementation evidence

Date: 2026-10-27. Status: **local implementation present; external verification pending**.
Step 6 is not fully complete. Management, tests and agentic summaries remain
disabled by default. No application database, live provider or deployed worker was used.

## Implemented files

| Files | Purpose |
| --- | --- |
| `backend/app/schemas/llm.py` | Bounded write-only requests, optimistic revisions, explicit public projections and profile settings |
| `backend/app/api/routes/llm_settings.py`, `api/router.py` | Tenant-scoped management routes, independent backend permission checks, no-store responses and sanitized validation/errors |
| `backend/app/services/llm/management.py`, `management_types.py` | Scoped management transactions, immutable profile versions, eligibility, operator permits and typed test accounting |
| `backend/app/services/llm/test_execution.py`, `test_worker.py` | Document-free delivery, fenced execution, durable admission and receipts, worker composition and bounded reconciliation |
| `backend/app/models/llm.py`, `llm_management_validation.py`, `models/__init__.py`, `models/domain.py` | Test records, scoped relationships, optimistic counters, immutable completed history and job scope |
| `backend/migrations/versions/d42a91c7e806_add_llm_management.py` | Additive schema, runtime grants/RLS, scoped qualification relationship and monotonic accounting protection |
| `backend/app/services/llm/credential_service.py`, `endpoint_policy.py` | Small compatibility seams: transactional credential mutation and approved-endpoint enumeration |
| `backend/app/core/config.py`, `worker.py` | Independent disabled-by-default gates and tasks on the existing worker/Beat configuration |
| `WBS_UI/src/services/llmApi.ts`, `llmModelDefaults.ts` | Existing API client integration, safe metadata types and form defaults |
| `WBS_UI/src/views/AiModelSettingsScreen.tsx`, `.css`, `App.tsx`, `components/AppLayout.tsx` | Dedicated permission-controlled AI Models screen and navigation |
| `backend/tests/test_llm_management*.py`, `WBS_UI/tests/ai-model-settings.spec.ts` | Isolated service/API/schema/worker tests, opt-in PostgreSQL checks and browser checks |

Existing migration-head contract tests were updated for the actual checkout head.
No dependency was added or upgraded by Step 6.

## API and permission contract

All routes use `/api/v1/tenants/{tenant_id}/llm`.

| Method/path | Permission | Behavior |
| --- | --- | --- |
| `GET /endpoints` | `llm:manage` | Operator-approved endpoint/auth scheme choices only |
| `GET, POST /connections`; `GET, PATCH /connections/{id}` | `llm:manage` | Scoped public metadata and optimistic updates |
| `POST /connections/{id}/credentials/rotate` | `llm:manage` | Explicit replace, rotate, clear or disable request |
| `GET, POST /profiles`; `GET, PATCH /profiles/{id}` | `llm:manage` | Manual exact model IDs and append-only settings versions |
| `POST /profiles/{id}/state` | `llm:manage` | Enable/default require current worker qualification; disable remains available |
| `POST /connections/{id}/test` | `llm:manage` | Authorized bounded synthetic probe or discovery request, HTTP 202 |
| `GET /connections/{id}/tests/{test_id}` | `llm:manage` | Sanitized scoped status, reservation counts and typed observations |
| `GET /usable-profiles` | `llm:use` | Usable metadata only; no credential access or administration |

Mutations require the current revision; stale updates return 409. Routes use
existing membership/permission checks, with fresh scoped authorization in service
transactions. Unknown roles are denied by the existing permission system.
List responses are bounded to 100 records. Tenant defaults retain the existing
unique index and serialize changes under a tenant lock. Errors omit raw input,
upstream bodies, encryption data and SQL details. Successful mutations/tests audit
resource/actor/tenant identities and credential-version metadata only.

## Credentials and endpoints

- Omitted credential input preserves the current value. Empty/null replacement
  input is rejected; it never erases a credential.
- `replace` encrypts a new secret; `rotate` re-encrypts the current secret into a
  new credential version; `clear` retires/removes the credential and disables the
  connection; `disable` blocks the connection while retaining the encrypted key.
- Connection CAS, metadata, credential version and invalidation share a SQL
  transaction. Existing Step 3 encryption/AAD/key-ring behavior is reused.
- Public metadata exposes `configured`, never a saved key or ciphertext.
- Admins select an approval ID. Provider/protocol and registered authentication
  schemes are validated against operator policy. Browser input cannot add hosts,
  ports, headers or network permissions.
- Secure transport, checked-IP dialing, TLS/peer validation, redirect/proxy/header
  restrictions and current credential resolution remain the Step 3/4 boundaries.

## Profiles and qualification

Settings include configured context/output ceilings, sampling, structured output,
tool mode, timeout, concurrency one, retry policy and run call/token/cost ceilings.
Configured ceilings are not advertised as observed limits. Unsupported protocol
controls and known unsupported capabilities are rejected. Editing a profile
creates a new immutable version and disables/default-clears the profile.

Connection mutations conservatively invalidate profiles and fence pending tests,
including credential rotation/replacement. A fresh test is required. Historical
versions remain available for provenance and cannot bypass a disabled connection.

Enable/default/catalog eligibility requires a succeeded persisted test, trusted
`live_worker` provenance, matching qualified version, current connection revision,
current operator endpoint-policy fingerprint and identical immutable settings.
The browser cannot submit capabilities. Fake transport success and standalone
live-network observations cannot promote capabilities.

Worker promotion additionally requires an operator-reviewed exact-fingerprint
limits record (context/output, worker identity and evidence UUID), current probe
binding/plan and supported required observations. Missing/unknown results leave
the profile unqualified. Promotion appends a version; it does not enable/default it.
Actual provider behavior and the positive live-worker promotion path remain
external qualification gates. In particular, a small protocol probe alone does
not establish large context capacity or JSON-action quality; operator evidence
must cover the configured modes/limits before provisioning the reviewed record.

## Document-free tests, delivery and recovery

Step 5's document-bound workflow outbox is deliberately unchanged. Step 6 adds
`llm_connection_tests`, containing an inline delivery record, configuration pins,
permit metadata, bounded ledger, receipts and sanitized outcomes. Test/job IDs
are the same UUID. The job, request and initial pending delivery commit together.
There is no fake document, ingestion run or summary workflow.

Publication claims are fenced; broker calls occur outside SQL transactions.
Messages contain only the test UUID and use a stable task identity. Duplicate
publication/acknowledgment ambiguity is handled by execution claims, not by a
claim of exactly-once provider execution. Reconciliation is bounded to 100 jobs,
delivery to five attempts, and each request expires within 60 seconds (or earlier
permit expiry). Execution has a 90-second fencing lease and no long SQL
transaction spans network I/O. A single bounded test needs no renewable lease.

Call/token reservations are committed before each outbound attempt. Probes make
one attempt per case; no format repair, automatic ambiguous replay or model
fallback is allowed. Reservations are never refunded on unknown billing. Worker
loss after any charged reservation terminates the request conservatively rather
than creating a new allowance. Credentials are resolved through the existing
authorization boundary before each send and result acceptance rechecks pins,
revocation, deadlines and fencing. Synchronous in-memory accounting methods are
unavailable on the durable budget.

The existing Celery test task now composes this document-free path independently
of the unfinished summary graph. A bounded reconciliation entry is added to the
existing Beat schedule only when tests are enabled. Task-owned NullPool engines
avoid sharing asyncpg connections across separate `asyncio.run` event loops.
Actual queue routing, single-slot deployment, scheduler uniqueness and crash
recovery on ARM64 remain unverified.

## Schema and compatibility decisions

Migration `d42a91c7e806` was based on initial head `b7e31d95a204`. It adds revision
counters, immutable settings/qualification references, a tenant/job composite
key and document-free test storage. PostgreSQL has FORCE RLS, scoped foreign
keys, runtime SELECT/INSERT/UPDATE only, bounded safe JSON and monotonic test
accounting/terminal-history guards. Runtime/migration roles remain separate.
Downgrade refuses to discard any test accounting/history.

During implementation, separate question-bank changes and merge migration
`c29f4b8e710a` appeared in the shared workspace, merging question-bank revision
`a13d9e7b602c` with `d42a91c7e806`. Those changes were preserved, not authored or
reverted by this Step 6 work. Existing migration-head assertions now follow that
merge. Older migrations were not rewritten.

Step 5 application-owned checkpoints, graphs, summary budgets and ingestion
outbox semantics were not redesigned. The prior generic connection-test guard
remains intact; only the concrete existing Celery test entry uses the Step 6 path.

## UI and secret exclusion

AI Models has its own `llm:manage` navigation and direct-route guard, separate
from member administration. Connection/profile forms are separate. Saved keys
never refill the password input; replacement values are transient and cleared
on successful submission, cancellation and tenant unmount. No key is put in
URLs, browser storage, telemetry, VITE configuration or test status.

The screen supports exact manual IDs, operator endpoint/auth choices, supported
provider controls, retry ceilings, qualification/default/availability states,
accessible alerts and bounded polling (60 checks, two-second interval). Testing
requires explicit synthetic-data/cost acknowledgment and identifies the provider
destination. The localhost/worker distinction is explained. Editors cannot open
administration; later summary-flow model selection was not added.

See [test results](test-results.md), [remaining inputs](remaining-inputs.md) and
[scope review](scope-review.md). These local checks do not establish production
readiness or complete the Step 6 exit gate.
