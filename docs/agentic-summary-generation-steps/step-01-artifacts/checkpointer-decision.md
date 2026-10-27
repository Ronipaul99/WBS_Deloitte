# LangGraph checkpointer qualification decision

Decision: **do not adopt the raw SQLite saver for production**. The Step 1 local
spike qualifies functional interruption/recovery and a test-only application guard.
The production PostgreSQL tenant/run transaction design remains unresolved.

Tested locally on Windows/Python 3.12 with LangGraph 1.2.18,
langgraph-checkpoint 4.3.1 and langgraph-checkpoint-sqlite 3.1.2.
Dependencies are pinned in `agent-qualification`; no production imports were added.

## Actual synthetic evidence

1. A real `StateGraph` writes a prepared counter, then interrupts for synthetic review.
2. The first child Python process exits and closes its SQLite connection.
3. A second child process reconstructs the graph and saver from the same disposable
   SQLite file, resumes with `Command(resume=True)`, and finishes. Prepared counter
   stays 1, review changes to true, and there are no pending nodes.
4. Repeating resume in a third process preserves final values and history length.
5. Two tenants have distinct synthetic markers in the same SQLite database.
6. A raw `SqliteSaver.get_tuple` can read tenant A with knowledge of its thread ID:
   **negative control reproduced**. The saver has no native application authorization.
7. The test-only `ScopedSpikeSaver` checks trusted tenant/run ownership before read,
   history/list and history cursor, checkpoint writes, pending writes, delete and
   delta-history calls. Cross-tenant, other-run and unknown-run attempts are rejected.
   Unscoped listing is rejected. Spoofed config tenant fields grant nothing.
8. Authorized state updates, history reads and deletion succeed; graph API calls
   also pass through the guard. An attempted second run for the same tenant is denied
   by the bound run. Ownership comes from the harness fixture registry, not thread entropy.

The harness has no LLM or external effects. LangSmith/LangChain tracing is explicitly
disabled in the spike/subprocess environment. Temporary pytest SQLite files contain
only synthetic data; no application settings, `.env`, network or production DB is used.

## Transaction and recovery limits

The guard authorizes **before** each supported synchronous saver operation; the
underlying saver then performs its own SQLite transaction. Authorization is not a
SQL row predicate or database-enforced RLS. Its immutable owner registry and
authenticated context are test fixtures, not production authentication. Direct
access to the underlying saver/connection bypasses it, as the negative control shows.
This is deliberately test-only and is not an installable application checkpointer.

Async saver APIs, real worker crashes, ownership revocation races, PostgreSQL RLS,
concurrent leases, migrations, cancellation, deletion races and provider charging
have not been qualified. A graph checkpoint cannot undo an external provider request.
Resume restarts an interrupted node; side effects before `interrupt()` need idempotency.

Before Step 5 adoption, choose a PostgreSQL checkpointer integration whose runtime
role cannot bypass tenant/run row restrictions. Inventory **every** read/write/list/
pending-write/history/delete operation; set trusted scope per transaction and bind
run ownership, including secondary connections/async paths. Test two tenants,
known thread IDs, same-tenant other runs, pooled-connection reuse, recovery, duplicate
delivery and revocation/deletion. Provision schema via reviewed migrations, never
runtime `setup()`. No such production persistence was implemented here.

References: [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
and [interrupt/resume behavior](https://docs.langchain.com/oss/python/langgraph/interrupts).
