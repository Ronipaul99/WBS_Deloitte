# Remaining Step 8 verification and inputs

Step 8 remains **partially complete**. Local synthetic implementation evidence
does not satisfy these external gates. Earlier Steps 1–7 outstanding inputs are
unchanged, including provider qualification, runtime-role PostgreSQL verification,
actual TLS, reviewed context capacity and deployed-worker recovery.

## Disposable PostgreSQL

No `docker`, `postgres` or `psql` executable was discovered in the current process,
and no explicit Step 8 disposable PostgreSQL inputs were present. The configured
application/Neon database was not read or used as a fallback.

Provision a fresh empty database named `wbs_step08_*`, with pgvector and separate
migration/runtime logins. Runtime must not be superuser, BYPASSRLS, inherit the
migration role or have public-schema CREATE. Supply only through the secure
test-process environment:

```text
STEP08_POSTGRES_MIGRATION_URL
STEP08_POSTGRES_RUNTIME_URL
STEP08_POSTGRES_DISPOSABLE_ACK=I_ACKNOWLEDGE_THIS_DATABASE_IS_DISPOSABLE
```

Run the isolated `tests/test_evidence_analyst_postgres.py` with `--noconftest`.
Its guard requires all inputs, matching database identity, separate roles and an
empty database. It migrates explicit supplied connections only and leaves the
synthetic database populated. Never delete existing data or substitute an
application URL to make verification pass.

The opt-in checks cover nested checkpoint/step serialization, rollback,
runtime-scoped reads, known-ID cross-tenant denial, absent-context/pool reuse and
immutability. They are not the full concurrent PostgreSQL recovery matrix.
Complete competing claims, cancellation/deletion/revocation races, leases,
fencing, budget monotonicity and continuation atomicity on PostgreSQL alongside
the outstanding Steps 2/3/5/6/7 checks before release.

## Worker, providers and quality

Separately qualify the actual Linux ARM64 worker, one processing slot, scheduler
uniqueness, broker routing, process restarts, credentials, checked-IP/TLS behavior
and the exact Mac/OpenAI/Claude profiles. No live calls or VM changes were made.
Provider access and possession of credentials are not permission for paid probes.
Live tests require explicit authorization and request/token/time/cost ceilings.

Actual analyst accuracy/omission/citation-entailment evaluation belongs to Step 14.
Canned adapter responses prove controller behavior only. No extraction accuracy
percentage or model-generated confidence is claimed.

Review real context/output limits and tokenizer/protocol overhead. The existing
Step 4 byte admission floor is retained, even if an approved tokenizer is injected;
small contexts can reject the analyst schema before any request. Existing message,
output, alias and citation bounds also fail explicitly rather than silently trim.
The Step 5 total deadline policy remains unchanged and may be too short for a
large tender; this step does not silently extend it.

## Later integrations and known limitations

- Writer, independent verifier, final quality gate, publication, approval, API and
  review UI remain later steps. No unfinished graph is connected to a summary API.
- Step 7 inventory and reading plan must be persisted/pinned by the trusted worker
  preparation boundary. The Step 8 composition hook consumes them; it does not
  auto-register preparation nodes or provision a runtime.
- Literal decimal rendering is supported; magnitude/unit conversion and supported
  cross-batch requirement dependency discovery remain unsupported here.
- Conservative identity collisions block ambiguous paraphrases rather than
  choose a winner. Broader semantic deduplication requires separate evidence.
- Bounded gap rounds do not exhaust every possible category search. Unknown,
  unavailable and unresolved categories must remain visible downstream.
- Existing canonical evidence lacks exact within-chunk cell/page mappings in some
  cases; Step 7 precision limits are retained without invented coordinates.
- No private PDF, cloud object or application database was fetched or queried.
  Historical RFP artifacts were not treated as current canonical-run evidence.
- Existing question-bank data remains untouched. Optional later consumption must
  preserve embedding identity, pinned document authorization and full coverage.
