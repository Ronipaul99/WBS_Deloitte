# Step 3: Secure credentials and provider endpoints

Status: independent local implementation verified, external verification pending,
2026-10-27. **Not fully complete**: PostgreSQL runtime-role/concurrency, live TLS
and worker-path qualification remain pending. See [implementation evidence](step-03-artifacts/implementation-evidence.md)
and [remaining inputs](step-03-artifacts/remaining-inputs.md).
Depends on [Steps 1](step-01-contracts-capability-qualification.md)
and [2](step-02-persistence-permissions.md); their pending qualification remains open.
Next: [Step 4](step-04-provider-adapters.md).

## Objective

Allow administrators to configure real API credentials and custom model gateways
without exposing keys or turning connection tests into unrestricted network access.

## Implementation tasks

1. Implement authenticated encryption using the repository's cryptography dependency.
   Bind ciphertext to tenant, connection, credential version, and encryption-key
   version using associated data. Use a fresh nonce for every encryption operation.
2. Load the encryption key from a separately provisioned runtime secret. Add a
   key-ring/active-key configuration contract and readiness failure for missing or
   malformed keys. Do not create example real keys or write encryption keys to DB.
3. Accept credentials through write-only request schemas. Omitted secret means
   preserve existing credentials; empty, clear, rotate, and disable must have explicit
   distinct semantics. Responses expose configured state, not decrypted values.
4. Define rotation behavior: a run pins endpoint/model/profile settings, while each
   provider call resolves the current authorized credential for that same connection
   and records its version. Disabling/revoking the connection blocks new calls,
   including retries; it does not silently select another provider.
5. Enforce an operator-approved egress policy for exact hosts, ports, path prefixes,
   and auth schemes. Tenant admins can select approved endpoints; they cannot
   authorize arbitrary access to VM internals merely by entering a URL.
6. Validate URL parsing, normalized origin/path, DNS results, and actual connection
   destinations. Block metadata/link-local, loopback, prohibited private/internal
   targets, embedded credentials, unsafe redirects, and rebinding bypasses. Apply
   this to discovery, tests, and inference, not just the initial save request.
7. Verify TLS normally. For the public Mac gateway, approve its reachable HTTPS
   host and authentication scheme. A future private gateway needs an explicit
   operator network exception; never disable the entire endpoint policy.
8. Restrict advanced headers to a registered adapter/gateway scheme. Prevent user
   control of Host, forwarding, proxy, or unrelated credential headers. Bound
   response size, connect/read timeouts, and error-body parsing.
9. Redact credential material from logs, exceptions, tracing, metrics, exports,
   connection-test results, and audit events. Audit changes by actor/record/version,
   not by secret value. Document encryption-key backup and rotation recovery.

## Proposed implementation targets

- `backend/app/services/llm/credentials.py`, `endpoint_policy.py`, and `errors.py`.
- Secret-file/environment settings in `backend/app/core/config.py`.
- Deployment secret references and examples containing placeholders only.
- `test_llm_credentials.py` and `test_llm_endpoint_policy.py`.

## Verification

Test encrypt/decrypt, wrong tenant/connection AAD, tampering, nonce uniqueness,
key rotation, lost-key failure, and omitted-key update semantics. Assert that no
response model includes decrypted keys. Use fake transports/DNS to test redirects,
IPv4/IPv6 representations, mixed public/private answers, rebinding, oversized
responses, and rejected internal destinations. Test an approved Mac gateway
without weakening the protections on other endpoints.

## Exit criteria

- [ ] A DB snapshot alone cannot recover credentials without the runtime key.
- [ ] Ordinary user APIs and frontend bundles cannot retrieve provider secrets.
- [ ] Every outbound provider operation applies endpoint policy and TLS verification.
- [ ] Revocation stops new calls; retries cannot use disabled connections.
- [ ] Rotation/recovery and redaction tests pass before real credentials are saved.

Local evidence: encryption, write-only metadata contracts, shared transport policy,
revocation/rotation, recovery and redaction have synthetic test coverage. The final
combined suite passed 511 tests; 14 PostgreSQL tests were skipped. These checkboxes
remain unchecked until the required PostgreSQL/runtime and live TLS qualification
has passed. No real credential or provider was enabled by this implementation.
