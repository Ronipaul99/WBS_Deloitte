# Remaining Step 3 verification and inputs

Step 3 is **partially complete**. Local synthetic evidence does not satisfy these
external gates. Do not save real credentials or enable providers until the required
security/persistence qualifications have passed.

1. Complete [Step 2 disposable PostgreSQL verification](../step-02-artifacts/remaining-inputs.md).
   Neither SQLite nor fake transports demonstrate PostgreSQL RLS or grants. No
   explicitly disposable PostgreSQL configuration or local Docker/PostgreSQL
   executable was available in this execution. No application/Neon DB fallback was
   used. Its 14 opt-in tests were skipped.
2. In a separately verified fresh disposable PostgreSQL database, exercise the new
   `CredentialService` under separate migration/runtime roles. Verify encrypted
   writes and existing AuthEvent INSERT permissions, current tenant predicates,
   absent-context RLS, cross-tenant reads/updates, membership revocation, atomic
   active-pointer changes, concurrent max-version allocation/row locks, rollback,
   and disable/rotate racing an attempt. No production grant or schema change is
   inferred from the local result. The frozen Step 2 migration was not modified.
3. Qualify the actual Python/httpcore/AnyIO/OpenSSL Linux ARM64 runtime and public
   HTTPS worker path with synthetic probes only, under separate authorization.
   Verify actual peer metadata, numeric dialing, no proxy route, hostname/SAN/CA
   failure handling, bounded reads/timeouts and connection closure. Fake TLS
   metadata tests do not establish live certificate compatibility.
4. Obtain the real Mac gateway's approved host, port, exact path prefix, protocol
   and registered auth scheme through a safe channel. Provision credentials/key
   ring separately. This execution does not contact it, OpenAI, metadata services
   or private/internal destinations. A private gateway exception is unsupported
   and fails closed; never weaken the whole public-IP policy to accommodate one.
5. Provision and independently back up the encryption ring through a secret
   manager/mounted owner-only file. Test real operational backup recovery without
   real document content. Verify Linux ownership/mode and Windows ACLs if used;
   no runtime secret file or key was created in this task.
6. Confirm monitoring/APM does not capture credential locals/headers or raw request
   validation errors. Only controlled public errors and metadata DTOs may cross
   future API/telemetry boundaries. Future adapters must use the shared transport;
   unsupported response/stream/auth behavior must remain unavailable.
7. Complete [Step 1 live-provider qualification](../step-01-artifacts/remaining-inputs.md)
   and later adapter capability testing before enabling any profile. No fabricated
   capabilities, successful provider tests or workflow isolation results were added.

No checkpointer, retry/lease executor, application route, model management UI,
summary agent, discovery implementation or inference adapter is part of this step.
