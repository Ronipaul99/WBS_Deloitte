# Remaining Step 6 verification and operator inputs

Step 6 is **partially complete**. Independent implementation and synthetic tests
do not qualify a real model, database role, worker or deployment. Keep summary
generation disabled; management/tests have separate disabled-by-default gates.

## Disposable PostgreSQL

Provision a fresh empty dedicated `wbs_step06_*` PostgreSQL database with pgvector,
separate migration/runtime roles, no runtime superuser/BYPASSRLS, migration-role
inheritance or public-schema CREATE. Supply securely to the test process only:

```text
STEP06_POSTGRES_MIGRATION_URL
STEP06_POSTGRES_RUNTIME_URL
STEP06_POSTGRES_DISPOSABLE_ACK=I_ACKNOWLEDGE_THIS_DATABASE_IS_DISPOSABLE
```

Run `python -m pytest --noconftest tests/test_llm_management_postgres.py -q` from
`backend`, with application configuration excluded as in the recorded test
runner. The fixture requires all three inputs, checks database identity and
emptiness, uses explicit connections and refuses populated databases. Never
substitute application/Neon URLs or delete shared data to make the check pass.

The four opt-in tests cover migration recovery preserving legacy/vector data,
runtime scope/grants, pooled scope reuse and basic locking/checkpoint continuity.
They are not the entire concurrent recovery matrix. Extend actual PostgreSQL
evidence to competing test/default claims, expired publishing tokens, interrupted
reservation/receipt/result commits, revoked memberships, cross-tenant foreign
keys and terminal/accounting triggers. SQLite tests do not establish any of these
PostgreSQL RLS/grant/locking guarantees. Prior Step 2/3/5 PostgreSQL gates remain.

## Operator configuration, not supplied or enabled here

Existing Step 3 keyring and egress policy must be securely provisioned and backed
up before credentials can be replaced/rotated. Management remains independently
controlled by `LLM_MANAGEMENT_ENABLED=false`; worker tests remain controlled by
`LLM_CONNECTION_TESTS_ENABLED=false`. `AGENTIC_SUMMARY_ENABLED` stays false.
Missing keys/policy/permits must remain unavailable rather than use a fallback.

For separately authorized live synthetic tests, provision to the API and worker:

- `LLM_TEST_AUTHORIZATIONS`: an operator-only JSON map keyed by the admin-visible
  candidate fingerprint. Values use the existing `LiveProbePermit` schema:
  connection ID, identical fingerprint, aware expiry, call/token/cost ceilings,
  reviewed input/output/request prices, review time and synthetic-only approval.
  Credentials being present is not permission to make paid calls.
- `LLM_WORKER_IDENTITY`: the actual operator-assigned worker identity.
- `LLM_TEST_REVIEWED_LIMITS`: an operator-only JSON map keyed by exact candidate
  fingerprint, containing reviewed `context_tokens`, `output_tokens`, matching
  `worker_identity` and a nonzero `evidence_id` UUID. This is a trusted release
  input, not a tenant-admin API or browser assertion. Obtain actual context,
  output/mode, tool and tokenizer evidence first. Do not fabricate these records
  to make the Enable button succeed.

These inputs are read by the runtime settings process. Coordinate API/worker
configuration reloads when changing operator policy/permits/keys; no live secret
reload or deployment automation was added. Restarting is an operator action,
not performed by this implementation. A test reservation or ambiguous request
must not be erased/reset during any recovery.

## Worker/provider qualification

Under separate explicit authorization and cost limits, verify actual existing
Celery/Redis/Beat routing, one processing slot, one scheduler, encryption access,
real TLS/checked-IP dialing and ARM64 dependencies. Verify worker loss before and
after submission, broker ambiguity, stale results, credential rotation/revocation,
permission removal and deadline expiry. An operator must resolve inaccessible
or revoked jobs; the reconciler does not bypass authorization to update them.

Qualify exact Mac gateway/OpenAI/Claude protocol, authentication, model identity,
JSON/schema/tool behavior, actual usage and reviewed capacity. Discovery failure
does not establish inference failure. Successful small probes alone do not prove
configured large context limits or untested JSON-action quality. Positive live
worker promotion, profile enable/default and usable-catalog behavior must be
confirmed on the actual restricted worker path. Fake observations remain fake.

No live calls, VM changes, migrations against application databases, feature
enablement or deployments were performed here. Steps 7 onward remain outside
this implementation; no evidence tools, summary agents, approval screens or WBS
generation were added.
