# Remaining Step 5 inputs and verification

Step 5 is **not fully complete**. The feature remains disabled and the existing
summary route is unchanged. No live provider, application/Neon database or VM was
used. Prior Step 1-4 pending qualifications remain pending.

1. Provision a fresh empty dedicated `wbs_step05_*` PostgreSQL database with
   pgvector, separate migration/runtime roles, no runtime superuser/BYPASSRLS,
   no migration-role inheritance and no runtime public-schema CREATE privilege.
   Supply only through a secure test-process environment:

   ```text
   STEP05_POSTGRES_MIGRATION_URL
   STEP05_POSTGRES_RUNTIME_URL
   STEP05_POSTGRES_DISPOSABLE_ACK=I_ACKNOWLEDGE_THIS_DATABASE_IS_DISPOSABLE
   ```

   Run `python -m pytest --noconftest tests/test_agent_checkpoint_postgres.py -q`
   from `backend`. The fixture refuses a nonempty database, runs frozen migrations
   directly on supplied connections, checks up/down/up preserving legacy/vector
   data, and leaves synthetic data for inspection. Never substitute application
   URLs or remove existing data to make it pass. Partial configuration fails.

2. The three opt-in tests are an initial migration/RLS/pool/locking check, **not**
   the complete release recovery matrix. Verify real concurrent claims, publisher
   token races, expired-worker completion, checkpoint/continuation atomicity,
   ledger monotonicity, revocation/deletion/cancellation races and active-revision
   CAS using the actual restricted runtime role. No SQLite result proves these.
   Complete the separate Step 2 PostgreSQL and Step 3 credential/RLS checks too.

3. Qualify the application-owned completed-node checkpoint design on PostgreSQL.
   Generic LangGraph saver operations are unsupported. A requirement for native
   framework pending writes, interrupts, time travel, nested namespaces or state
   edits needs a separately reviewed scoped design, schema and isolation tests;
   never introduce an unguarded saver as a shortcut.

4. Qualify the implemented `SqlWorkerRuntime` routing/composition boundary.
   ID-only messages must resolve to authenticated tenant/requester/run scope,
   with current checks in every transaction. Bounded reconciliation enumeration
   must not bypass protected table RLS. A generic SQL resolver is implemented and
   synthetically tested, but no production runtime instance is installed here.
   Real evidence/analyst/writer/verifier/publication implementations belong to
   later steps; test handlers must never be registered as production nodes.

5. Resolve the document-free connection-test persistence gap before real worker
   probes: persist authorized test identity, pinned configuration, permit and
   durable admission/receipts without a document or fake processing run. The
   generic synthetic worker executor exists; live execution fails closed until
   this durable request/recovery boundary is implemented and qualified. Do not
   reset a paid test's allowance on redelivery or infer live qualification from
   its fake transport report. Management routes/UI remain Step 6 scope.

6. Under separate authorization, verify actual Linux ARM64/Celery/broker crashes,
   single-slot CLI/runtime concurrency, one existing Beat scheduler, safe shutdown,
   real TLS/checked-IP dialing, encryption keys and real provider qualification.
   Local worker configuration does not establish deployed topology. No live
   request, secret provisioning or infrastructure change was authorized here.

7. Test operational deadline selection and artifact/ledger storage bounds against
   representative qualified profiles. Current Step 2 policy constrains the total
   run deadline to the pinned timeout; this may be too short for a long PDF.
   Do not silently extend deadlines or reclassify the byte admission estimate as
   actual tokenization/usage. Any policy contract change requires explicit scope
   and tests.

No Step 5 release exit criterion is marked fully satisfied based on mocks alone.
