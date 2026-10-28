# Step 6 recovery, ownership and fault matrix

Date: 2026-10-29. These are application contracts and synthetic local observations, not live upstream, PostgreSQL or deployed-worker qualification.

## State ownership and legal transitions

| Layer / owner | State and transition | Safety boundary |
| --- | --- | --- |
| Application submission intent | `SUBMIT_PENDING` -> `SUBMITTING` | Commit scoped intent before identifier-only delivery; claim a bounded attempt and owner token before HTTP. |
| Application submission attempt | `SUBMITTING` -> `ACKNOWLEDGED` | Validate bounded acknowledgement and preserve the returned job UUID only while the fence is current. Acknowledgement alone does not establish database ownership. |
| Safe pre-send failure | `SUBMITTING` -> delayed `SUBMIT_PENDING`, or terminal rejection at the attempt bound | Only failures classified as not submitted may retry. A retry resolves current server configuration; the durable attempt count does not reset. |
| Potentially submitted / lost worker | `SUBMITTING` -> `SUBMISSION_UNKNOWN` | No automatic remote POST. An expired claimed attempt is conservative even if it might have died before sending; there is no durable proof of an unsent request. |
| Ineligible submission | -> `REJECTED` | Revoked authorization, incompatible source/configuration or exhausted attempts fail closed. No fallback job. |
| Shared external Job / remote worker | Raw `RUNNING` projects to `IN_PROGRESS`; supported completion requires completed status and progress 100 | This application reads the exact acknowledged ID, type, tenant, project and JSON document identity. It does not normalize the stored execution row. |
| Application binding projection | `PENDING` / `WAITING_FOR_JOB` -> `VERIFIED`, or `UNAVAILABLE` / `STALE` | Visibility grace rereads the same ID; wrong scope never causes a latest-job search. Compatible workflow bindings preserve historical `Job.workflow_id`. |
| Application import | `WAITING` -> `VALIDATING` -> `IMPORTED` | Short scoped claim, bounded validation snapshot, digest and canonical checks, fenced atomic acceptance. Missing payload returns to bounded waiting; expired local leases permit local recovery only. |
| Invalid / stale import | -> `INVALID` / `STALE` | Bad contract/provenance, expired visibility allowance or changed lifecycle/revision cannot become review-ready. No generation replay. |
| Already imported request | `IMPORTED` remains immutable | Return its saved summary identity/imported revision; do not restore generated content over later edits or approval. |
| Summary review / application and explicit human action | Original generated content plus separate current edits; actual change advances revision and clears approval | No-op preserves revision/approval. Approval requires the authoritative expected revision and current source/authorization. Approval does not establish semantic verification or enable unsupported WBS. |
| Browser observer | Pending -> live progress -> import pending -> matching persisted review, or paused/error | Sequential bounded GETs; late-response guards; resume/check-status never POST generation. Closing the browser does not cancel durable work. |

Identity remains separate at each layer: request, external job, tenant/project/document, pinned processing run, workflow association, summary and content revision. Generated evidence and editable current content remain separate. Section citation numbers are local namespaces.

## Transaction and permission boundaries

The existing submission/import code uses `ensure_tenant_transaction` on new worker sessions. The test plugin and full-stack harness enforce the active-transaction precondition even on SQLite. No session-global tenant setting, guard removal or arbitrary query to trigger autobegin was introduced.

The existing document guard precedes review's sorted workflow locks and summary lock. Import also starts with the document/source guard before accepting changes. Reconciliation keeps HTTP and broker work outside database transactions. True PostgreSQL lock ordering, deadlock behavior, pooled RLS and competing writers still require disposable PostgreSQL.

Step 6 adds a fresh account, tenant, membership permission and authentication-version check after awaited review locks. The previous route-admission permission object alone was stale when authorization changed during that wait. The recheck prevents the reproduced stale admission; it is not a claim that a revocation occurring after the final check is serialized with the mutation on PostgreSQL.

## Controlled fault and security matrix

The named tests execute production routes/services. SQLite checks establish application behavior, not restricted-role RLS or concurrent PostgreSQL guarantees.

| Boundary | Actual local evidence | Result / limitation |
| --- | --- | --- |
| Intent commit failure | New `test_intent_commit_failure_leaves_no_delivery_or_partial_request` | Rollback leaves no request and no delivery; a subsequent ordinary submission succeeds. |
| Committed intent / delivery failure | Existing submission tests; new publish-then-raise test; full-stack paused delivery pump | Intent survives; IDs only; duplicate processing submits once. Pump recovery is not broker process recovery. |
| Claim / expiry / replaced owner | Existing submission and import fence/lease tests | Active owner blocks another claim; expired/superseded owner cannot accept. True simultaneous restricted-role PostgreSQL claims pending. |
| Safe connect failure / synthetic key rotation | New safe-retry test | Second attempt uses newly supplied synthetic server key; durable count advances to two; no secret acknowledgement. |
| HTTP after-submit / lost acknowledgement | New database-ack fault and full-stack fake-service 503-after-create | Durable unknown outcome, no blind repeat POST, no fabricated acknowledged ID or draft. |
| Binding / multiple jobs / visibility | Existing exact-job tests; full-stack newer unrelated completed job | Same acknowledged ID only; metadata reads exclude result JSON; scope/type/document mismatches fail closed. |
| Completion / missing payload | Existing bounded grace tests and full-stack completed-99 / missing-payload split | No premature import; later same-row payload can import; grace expiry remains explicit in service tests. |
| Validation / acceptance digest / canonical source | Existing import change-between-validation-and-acceptance tests | Changed result, source, membership, revision or canonical evidence cannot be accepted. |
| Summary / workflow / marker write | Existing three-boundary fault injection and post-commit failure tests | Rollback leaves no partial readiness; local retry returns one import identity. |
| Save / approval / import replay | Existing review tests and actual backend/UI edit/reload/no-op/approval scenarios | Stale expected revisions reject; replay preserves human work; actual edit resets approval; no-op preserves it. True simultaneous PostgreSQL races pending. |
| Authorization during review lock wait | New eight-case save/approve matrix | Account disablement, tenant disablement, role removal and auth-version change return 403 without revision/approval mutation. Both role cases returned 200 before the fix. |
| Allowed / denied roles | New ADMIN/EDITOR positive checks; existing VIEWER/unknown-role and foreign-scope tests | Existing permission semantics preserved for read/status/edit/approve; backend denial independent of UI. |
| Source deletion / replacement | Actual deletion API and cleanup entry point, then same-byte fresh-key upload | Pending deletion blocks upload; completion permits new document identity; no old request/summary association transfers. Broader retention hard-purge ordering remains outside scope. |
| Browser delayed reads/saves / scope switch | Existing mocked component suites | Abort/late-response, tenant/logout, retained conflicts and read-only status recovery pass. These are mocked browser evidence, not process-level backend cancellation. |
| Network / secrets | Existing production transport tests, fake loopback boundary, browser header/storage tests, bundle marker scan | Fixed origin/path, TLS/redirect/proxy and bounded-I/O construction retained. No real upstream TLS observation; no `result_url` fetch. |
| Hostile data | Existing strict contract/provenance/size tests; new deeply nested payload test | Bounded sanitized rejection; no input echo or silent truncation. Plain-text UI and local citation namespaces preserved. |

The upstream has no qualified idempotency/correlation or remote cancel/retry contract in this task. Fake-service behavior cannot supply that qualification. Unknown billing/execution remains unknown.
