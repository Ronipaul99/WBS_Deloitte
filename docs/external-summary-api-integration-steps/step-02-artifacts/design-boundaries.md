# Step 2 design and prerequisite gaps

Date: 2026-10-28. Status: implementation in progress; qualification is not claimed.

Baseline: Step 1 source changes and the staged planning documents already exist. Initial Step 1 file fingerprints were captured in ignored `backend/.data/external-summary-step02/baseline.json`. No historical migration, secret, application database or frontend changes are authorized.

## Demonstrated persistence gaps

Step 1 has one originating workflow per request, but a compatible reused request does not remember template-fork associations or the workflow checkpoint expected at attachment. It also lacks a persisted database-verification marker. Binding solely by `Job.workflow_id` would steal another workflow's execution ownership.

The narrow Step 2 extension is therefore:

- Nullable `summary_api_requests.database_verified_at`.
- A `summary_workflow_bindings` association holding trusted tenant/project/document/request/workflow identity, expected checkpoint, previous summary-job pointer and verification timestamp.
- Composite unique constraints on existing request/workflow identities so association foreign keys prevent cross-document scope mixing.
- Additive migration from Step 1 head `d82f6a913b70`, with FORCE RLS and separate restricted runtime-role grants. Historical migrations remain unchanged.
- Submission creates/retains the association within its existing transaction; it does not verify an external job there.

Pre-Step-2 requests without an association are not silently backfilled with invented historical checkpoint expectations. They return an explicit association-unavailable state until an authorized compatible submission explicitly attaches them. This does not submit another remote generation request when the intent is acknowledged.

## Tracking policy

Exact ID/type/tenant/project/canonical request-document predicates and JSON-object validation apply. Queries project metadata columns only, never `result_payload`, raw error fields or full request JSON. A same-tenant ID-only check can distinguish contract mismatch; RLS-hidden foreign rows remain indistinguishable from missing and are unavailable after visibility grace. No cross-tenant existence oracle is added.

Wire status policy: `RUNNING` is sampled. `COMPLETED` and `completed` implement the user's described completion contract. `QUEUED`, `FAILED` and `CANCELLED` are explicit defensive supported lifecycle values in synthetic tests, not live-qualified provider observations. Other case/values fail closed. Completion requires progress exactly 100 and remains IMPORT_PENDING.

Generic job GET/events/cancel/retry can otherwise expose results or mutate external rows. External identities are rejected before full ORM Job loading and directed to the scoped metadata endpoint. Legacy behavior remains separate.

Workflow recovery gains external metadata; it does not load results, publish output or dispatch generation. Matching historical WBS workflows remain historical. Completed-but-unimported external work cannot reopen an older summary as new success.

Required PostgreSQL/RLS, shared upstream contract, live TLS and deployed-worker qualification remain pending from Step 1. No live service call or feature enablement is included.
