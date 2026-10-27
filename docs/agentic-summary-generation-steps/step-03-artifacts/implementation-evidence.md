# Step 3 implementation evidence

Date: 2026-10-27. Status: **independent local implementation verified; Step 3 is
not fully complete**. Step 1 live-provider qualification and Step 2 PostgreSQL
verification remain pending. No provider or LLM feature was enabled.

## Implementation

| File | Purpose |
| --- | --- |
| `backend/app/services/llm/credentials.py` | AES-256-GCM envelopes, scope/version AAD, bounded runtime key ring, write-only update contract, metadata-only status/audit/receipt |
| `backend/app/services/llm/credential_service.py` | Admin-only lifecycle operations; fresh tenant/member checks, current credential resolution and authorization before each transport write |
| `backend/app/services/llm/endpoint_policy.py` | Operator approvals, exact origin/path/auth/purpose policy, conservative public-IP validation and bounded DNS resolution |
| `backend/app/services/llm/secure_transport.py` | Shared HTTPS JSON transport; checked numeric-IP dialing, actual peer checks, original-host TLS/SNI, bounded I/O and no redirect/proxy/retry path |
| `backend/app/services/llm/errors.py` | Controlled error codes and correlation IDs without upstream exception/body disclosure |
| `backend/app/services/llm/redaction.py` | Task-local suppression of sensitive low-level transport diagnostics, including exception and extra fields |
| `backend/app/services/llm/security_config.py` | Lazy runtime security loading and metadata-only readiness primitives; no startup or route integration |
| `backend/app/core/config.py` | Default-disabled settings for separately supplied key-ring/file, active version and operator policy; secret inputs excluded from serialization/repr |
| `backend/pyproject.toml` | Direct `httpcore[asyncio]==1.0.9` dependency for its public network backend/stream API; this exact version was already installed transitively |
| `backend/tests/llm_security_fixtures.py` | Ephemeral keys, synthetic rows, SQLite foreign keys, fake DNS and an in-memory HTTP wire backend |
| `backend/tests/test_llm_credentials.py` | Encryption, validation, readiness, permissions, atomic lifecycle, lost-key and pinned-settings tests |
| `backend/tests/test_llm_endpoint_policy.py` | URL/DNS/peer/TLS/header/rebinding/revocation/response-bound/error/redaction tests |

There are no schema changes or changes to the Step 1 contracts, Step 2 models,
repositories, permissions or migration. The credential service reuses the existing
`llm_connections` and `llm_credential_versions` tables and `ScopedStorage` predicates.
It owns short transactions because current authorization must be refreshed between
attempts and immediately before writes. No transaction is held across network I/O.

`EndpointPolicyRecord.approval_id` selects an operator-owned approval containing the
authentication scheme and allowed operation purposes. Tenant metadata must match
the exact host, port and path prefix. This needs no additional storage column.
The existing `AuthEvent` table stores typed metadata for lifecycle changes and
attempt authorization. No generic secret/header/transcript payload is accepted.
PostgreSQL grants/RLS and concurrent row-lock behavior for this path still need
verification under the real disposable runtime role.

## Evidence and limits

- [Credential lifecycle, configuration and recovery](credential-lifecycle-recovery.md).
- [Endpoint and transport enforcement](endpoint-transport-boundary.md).
- [Executed tests and commands](test-results.md).
- [Remaining verification and external inputs](remaining-inputs.md).

All network tests use controlled fake DNS and fake network streams, including the
synthetic public Mac gateway. No real TLS handshake, provider compatibility,
production RLS or worker reachability result is inferred from these tests.

No API routes, UI, provider adapters, discovery implementation, inference call,
graph, scheduler, production checkpointer or dispatch/retry worker was added.
No local runtime environment/credential file, deployed service, CI workflow or VM
was edited. Nothing was deployed, committed or pushed. Pre-existing checkout
changes were retained; the final hash comparison is recorded in test-results.md.
