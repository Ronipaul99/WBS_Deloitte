# External summary API integration: implementation steps

Prepared: 2026-10-28 (Asia/Calcutta).

Status: planned; creating these documents does not implement or qualify the integration.

Master plan: [External summary API integration](../external-summary-api-integration-plan.md).

## The six implementation steps

Implement in this order. There are no additional implementation phases outside these six steps; contract checks, configuration, persistence and verification belong to the step that needs them.

| Step | Implementation document | Outcome | Dependencies |
| --- | --- | --- | --- |
| 1 | [Backend-only API submission and secret handling](step-01-backend-submission-secret-handling.md) | Authorized durable submission, fixed HTTPS transport, server-held secret and typed acknowledgement. | Inspect current checkout and external contract. |
| 2 | [Exact `DOCUMENT_SUMMERIZATION` job tracking](step-02-exact-job-tracking.md) | Bind and read the exact scoped shared job; normalize status without rewriting it. | Step 1. |
| 3 | [Live status, step and progress display](step-03-live-status-step-progress.md) | Actual per-poll progress in the existing workflow screen with bounded waiting. | Steps 1-2. |
| 4 | [Completed-result validation and persistence](step-04-completed-result-validation-persistence.md) | Validate and import the completed payload once into a saved, unapproved review draft. | Steps 1-2; independent of the browser staying open. |
| 5 | [Seven-section UI mapping, citations and draft editing](step-05-seven-section-review-editing.md) | Lossless structured review, truthful confidence, safe saves and preserved evidence. | Steps 3-4. |
| 6 | [Recovery, duplicate prevention, security and end-to-end tests](step-06-recovery-security-end-to-end.md) | Failure recovery, concurrent safety and evidence across the complete integration. | Steps 1-5. |

## Fixed integration decisions

- The external service writes to the same PostgreSQL `jobs` table as this application.
- The finished response is in `jobs.result_payload`; the external service does not write `document_summaries`.
- The exact external type is `DOCUMENT_SUMMERIZATION`. Keep legacy `DOCUMENT_SUMMARY` history compatible.
- The service owns its job status/progress/result. This application owns scoped coordination, review content and human approval.
- Browser requests use this backend; the API key never reaches the UI.
- A request UUID and an external job UUID are distinct. Do not create a second generation job to bridge them.
- Completion requires confirmed completed status and progress 100, followed by successful result validation/import before review becomes ready.
- Preserve project navigation, document dialogs, uploads/deduplication, ingestion, embeddings, WBS algorithms and authentication semantics.

## Execution discipline for every step

1. Read repository instructions, this index, the master plan, the selected step, preceding implementation/artifacts and relevant current code. Later steps are context only.
2. Capture initial git status/diff and actual schema/migration head as applicable. Repository snapshots in the master plan are not a substitute for current inspection.
3. Implement only the selected step and directly necessary compatibility changes. Preserve pre-existing/concurrent edits. Do not silently fill a prerequisite gap with another architecture.
4. Keep the integration disabled while incomplete. No real service calls, private documents, secret provisioning, application-database checks, environment edits or deployment are authorized by these documents.
5. Use synthetic credentials/inputs and controlled transports. Inspect `backend/tests/conftest.py`; isolate backend tests with `--noconftest` and do not delete `.test-data`.
6. Use verified disposable PostgreSQL databases and restricted runtime roles for RLS/migration/concurrency checks. Never migrate, downgrade, truncate or broadly delete the application/Neon database. SQLite success is not PostgreSQL verification.
7. Run focused tests and relevant earlier-step regressions, lint/type/build checks for changed areas and `git diff --check`. Review the final diff against the baseline.
8. Record actual evidence in this directory's `step-NN-artifacts/`. Include files/reasons, commands/results, exit criteria, unresolved inputs and verification limitations. Do not commit keys, private payloads or raw sensitive logs.

Do not modify actual `.env`/secret files, Docker/Nginx configuration, CI workflows or the live VM. Do not commit, push, enable features or deploy. Placeholder settings in example documentation are allowed only where specified.

## Handoffs and completion reporting

Each step document names its input/output contracts and exact boundaries. Security and duplicate-prevention basics are required as soon as their code exists; Step 6 verifies and hardens them rather than making earlier unsafe code acceptable.

For each implemented step report:

- Files changed and why.
- Tests/checks actually run, with pass/fail/skip counts where available.
- Local exit criteria satisfied.
- Remaining upstream, PostgreSQL, worker or live-network qualification.
- Confirmation that later-step functionality and live-environment changes were excluded.

“Locally implemented” and “live qualified” are different statuses. Missing external idempotency, status vocabulary, scope fields or source-lineage guarantees must remain explicit. Synthetic fixtures never establish real provider quality or deployed service compatibility.
