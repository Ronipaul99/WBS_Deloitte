# Admission budgets, qualification and provenance

## Caller-owned budget

`CallBudget` is an in-process admission ledger, shared by the caller across tasks,
retries, format repair, probes and discovery for one pinned provider/profile/endpoint.
It is not a production workflow store, durable retry executor or billing service.
An asyncio lock serializes its operations; there is no new worker or scheduler.

| Bound | Behavior |
| --- | --- |
| Shared requests | 1-120 admissions; cannot exceed the pinned profile's maximum |
| Shared tokens | 1-1,000,000 reserved tokens; cannot exceed the profile total |
| Shared time | Positive monotonic deadline up to 3600 seconds |
| Per-invocation attempts | 1-8, default 3; retries and repair share this ceiling |
| Format repair | At most **one request across the shared ledger**, without replaying invalid output |
| Repair failure | No retry of the repair; no second format-repair request |
| Backoff | Default 0.25s exponential; policy delay bounded to 30s maximum |
| Retry-After | Standard integer seconds or HTTP date; bounded metadata; a delay above the policy/deadline stops retry rather than retrying too early |
| Timeout | Effective attempt limit is the minimum of profile timeout, shared remaining time and the operator transport ceiling |

Every attempt reserves its complete input/output allowance. Reservations are not
refunded after missing usage, failures or ambiguous submission. Input admission uses
serialized UTF-8 payload bytes plus fixed headroom, including instructions, schemas
and replay history. This is a conservative client estimate, **not** an actual model
tokenizer measurement or proof of server context capacity. No document is silently
truncated to fit. Real tokenizer/context qualification remains pending.

Reported usage comes from explicit valid provider counts. Missing, partial or invalid
counts are unknown, never zero. If any attempt has unknown usage, combined usage is
unknown while individual known counts remain available in metadata. A server that
reports exceeding requested ceilings cannot publish successful output or receive
another admission on that ledger. Late responses cannot publish success after the
shared deadline.

Default retries cover 429 and transport failures known to occur before submission.
Retrying 502/503/504 or an ambiguous submitted timeout requires an explicit policy.
Write submission is conservative: a partial/failed write may already have reached
the provider. No exactly-once billing, no idempotent external execution and no
automatic fallback are claimed. Auth/configuration, endpoint-policy, revocation,
refusal and truncation failures are not repaired or bypassed.

Attempt records contain only request/sequence/outcome, normalized stop reason,
usage, bounded HTTP metadata and the Step 3 credential receipt. They contain no
raw prompt, invalid response, error body, key or hidden reasoning. Each new attempt
resolves its current credential through the same secure transport; rotation changes
the receipt version and revocation blocks subsequent writes. Cancellation propagates,
does not become a retry, and records conservative unknown usage. When cancellation
prevents receipt recovery, the local record leaves it absent rather than inventing
a credential version; the existing credential service records admission separately.

## Qualified inference versus candidate probes

Normal `generate` requires a trusted `QualificationBinding` matching the exact
profile/capability identity, tested time, approved endpoint and adapter options.
Its fingerprint includes capability metadata and relevant profile settings;
changing those invalidates it. Real-network inference additionally requires an
enabled profile with `live_worker` qualification. Synthetic transports require
synthetic qualification and cannot attest live-worker execution.

Candidate probing is separate from normal generation because a pending Step 1
profile correctly lacks qualified limits/features. Probes use fixed synthetic
messages, declared small ceilings and parser context identifying only what was
requested. They never invent `ProviderCapabilities` to bypass validation.

`CapabilityReport` returns observations with UTC time, connection/profile/version,
configuration fingerprint, actual tested input/output/time settings, effective
timeout, origin, credential receipt, outcome and usage. `is_current` checks the
profile/endpoint/options and exact probe plan. Candidate fingerprints exclude the
observations themselves; inference bindings separately bind qualified capabilities.
An exact-model probe without model identity remains inconclusive. One small output
probe does not establish a complete context window or long-document reliability.

Transport origin is derived from trusted construction: any injected resolver/backend
is synthetic. The report distinguishes `synthetic_fixture` and `live_network`;
even a real network probe is **not** automatically `live_worker` qualification.
No report enables or persists a connection, profile or capability. Trusted storage,
worker-path evidence and the eventual model-management approval flow remain required.

## Explicit live-probe authorization

No live permit was issued or used here. A future real-network probe additionally
requires separately authorized server-owned `LiveProbePermit`, bound to the exact
connection/configuration fingerprint and expiration. It includes request/token
ceilings, an explicit cost ceiling, separately reviewed input/output rates, request
fee and pricing-review time. A conservative allowance must fit that ceiling before
admission. No vendor price/rate is hard-coded or automatically fetched. These are
operator-approved estimates, not a guarantee of the provider's eventual invoice.

Do not accept permits, qualification references or trusted profiles directly from
client/model JSON. Future connection-management routes must independently enforce
tenant-admin permission before constructing these primitives. Permit presence
does not bypass scoped credential authorization, connection disable/revocation,
operator endpoint policy or TLS. Credential availability alone authorizes no live
probe. Existing startup and `.env` behavior remain unchanged.

Model listing is one bounded page through the discovery boundary, with no returned
URL followed. Unsupported/missing listing returns an unavailable observation;
manually supplied model IDs remain valid candidates for independent inference
tests. The list is never used to silently substitute a different model.
