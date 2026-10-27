# Step 6: Add model management APIs and administrator UI

Status: local implementation present; PostgreSQL, live-provider and deployed-worker
qualification pending, 2026-10-27. Step 6 is not fully complete. Management/tests
and summary generation remain disabled by default. Depends on Steps 2-5.
See [implementation evidence](step-06-artifacts/implementation-evidence.md),
[test results](step-06-artifacts/test-results.md) and
[remaining inputs](step-06-artifacts/remaining-inputs.md).
Previous: [Step 5](step-05-durable-orchestration.md).
Next: [Step 7](step-07-pinned-evidence-coverage.md).

## Objective

Let tenant admins configure/test model connections and profiles, while editors
can discover and later select approved models without seeing their credentials.

## API contract

All paths below are under `/api/v1/tenants/{tenant_id}/llm` and enforce tenant
scope plus the explicit permissions from Step 2:

| Operation | Contract |
| --- | --- |
| List/create/read/update connections | Return public connection metadata only; credential fields are write-only |
| `POST /connections/{id}/credentials/rotate` | Store a new encrypted credential version and audit the change |
| `POST /connections/{id}/test` | Create a bounded synthetic test job through the Step 5 outbox |
| List/create/read/update profiles | Reference a connection and immutable model/settings/capability versions |
| Enable/default/disable profile | Enforce successful current capability qualification and tenant/workflow scope |
| List usable profiles | Editor-safe catalog with model/capability/status metadata, never decrypted credentials |

Use ID-scoped resource routes and optimistic version checks for mutations. Do not
encode the full provider URL or a secret in a route/query string. Connection tests
return sanitized status and capability results, not raw upstream bodies.

## Implementation tasks

1. Add request/response schemas, authorized routes, scoped service methods and audit
   events. Require `llm:manage` for changes/tests and `llm:use` for usable-model access.
   A test can incur a small inference charge; explain its synthetic scope in the UI.
2. Separate provider connection forms from model profile forms. Add provider/API
   format presets, approved base URL, auth scheme, password-style API key input,
   and configured/replace-secret state. Never refill the real saved API key.
3. Support exact model ID entry even when discovery is unavailable. Show only
   verified settings: context/output limits, sampling support, JSON/tools mode,
   concurrency, timeout, retry, and run token/call/cost ceilings.
4. Connection/model/endpoint changes invalidate incompatible capability results.
   Keep old non-secret profile versions available for historical provenance, but
   disabled connections must not become usable through an old version.
5. Add a dedicated AI Models settings screen and navigation permission. Do not
   attach credential administration to `member:read` or ordinary editor access.
6. Run synthetic tests from the actual worker and show queued/running/pass/failure
   state. Explain that `localhost` refers to the Oracle runtime, not the Mac.
7. Show the selected default, last qualification time and unavailable/disabled
   states. Selecting a cloud model identifies the destination before generation;
   never silently substitute it when the Mac is unavailable.

## Proposed implementation targets

- `backend/app/api/routes/llm_settings.py`, `schemas/llm.py`, and LLM repositories.
- `WBS_UI/src/views/AiModelSettingsScreen.tsx`, related styles and `services/llmApi.ts`.
- App navigation/auth permissions and configuration tests.

## Verification

API tests: admin success, editor/viewer mutation denial, cross-tenant ID denial,
masked responses, rotation, disabled profiles, stale capability versions,
synthetic-test limits, and preservation when the API-key field is omitted.
UI tests: secret replacement without echoing a saved key, manual model entry,
provider-specific controls, accessible error/progress state, and no key in browser
storage. Inspect test responses/bundle configuration for credential leaks.

## Exit criteria

- [ ] Admin can configure/test approved providers and enable a model profile.
- [x] Editor-safe metadata and administration denial verified locally; live catalog eligibility remains pending.
- [x] Capability/configuration failures are visible and synthetic success cannot enable a profile in local tests.
- [x] Credential exclusion from response payloads and frontend persistence verified with synthetic inputs.
- [x] Connection tests use synthetic-only probes with no source-document reader; local SQL access checks pass.

The first exit criterion (configure/test/enable on the actual worker) remains open.
Checked local criteria do not establish PostgreSQL RLS, actual TLS/provider
compatibility, deployed recovery or release readiness.
