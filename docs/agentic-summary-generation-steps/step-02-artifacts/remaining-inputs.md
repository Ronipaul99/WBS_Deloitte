# Remaining Step 2 verification

Step 2 is **not fully complete**. Local schema/repository/permission and SQLite
migration checks passed. No actual PostgreSQL migration, RLS, grants, trigger,
runtime-role or concurrent-transaction result is claimed.

This workspace has no discovered `docker`, `psql`, or `postgres` executable and no
explicit disposable PostgreSQL test variables. The configured application/Neon
database was not used as a fallback. No VM connection or service change was made.

## Disposable PostgreSQL requirements

Provision a fresh, empty dedicated database with a name starting `wbs_step02_`,
pgvector available, a migration owner able to install the existing schema, and a
separate runtime login. Runtime must not be superuser, have BYPASSRLS, inherit the
migration role, or have CREATE privilege on public. Both URLs must identify the
same host/port/database. Use synthetic inputs only.

Provide these through a secure **test-process environment**, not `.env` or Git:

```text
STEP02_POSTGRES_MIGRATION_URL
STEP02_POSTGRES_RUNTIME_URL
STEP02_POSTGRES_DISPOSABLE_ACK=I_ACKNOWLEDGE_THIS_DATABASE_IS_DISPOSABLE
```

Then run from `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest --noconftest tests/test_agent_schema_postgres.py -q
```

The integration fixture refuses a nonempty database, does not read application
settings/URLs, and runs the frozen historical migrations directly with the supplied
disposable connection. It seeds synthetic legacy/vector data, performs empty-new-
schema up/down/up checks, and adds synthetic agent records. It deliberately leaves
the disposable database populated; recreate it before a subsequent full run.

Required results: runtime-role RLS/grants and absent-context denial; known checkpoint
IDs with wrong tenant/run; credential/evidence/outbox composite scope; duplicate
step/outbox/checkpoint identities; immutable revisions and audit history; active
pointer/approval version checks; transaction-context reset; preserved legacy text
and embeddings; populated-downgrade refusal. Fix any failures before marking the
PostgreSQL exit criteria complete. Concurrent ownership/revocation/deletion races
and a production LangGraph saver remain later orchestration/lifecycle qualification.

Step 1 Mac/OpenAI worker-path qualification also remains pending. Do not infer live
capabilities from fixtures or enable a real profile. This step adds no provider
adapter, credential encryption, endpoint-security system, application route or UI flow.
