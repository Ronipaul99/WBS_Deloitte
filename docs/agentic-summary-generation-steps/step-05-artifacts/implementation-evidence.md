# Step 5 implementation evidence

Date: 2026-10-27. Status: **partially complete**. Local synthetic implementation
does not establish PostgreSQL or deployed-worker qualification. Nothing is enabled.

## Changed files and responsibilities

| Files | Purpose |
| --- | --- |
| `backend/app/services/agents/state.py`, `graph.py` | Bounded Pydantic cursors, typed node completions, explicit transitions, one graph repair, version checks, a real LangGraph invocation per durable node, disabled external graph tracing |
| `storage.py` | Atomic run/job/outbox creation, current authorization/source/profile/endpoint checks, scoped row locks, fenced claims/completion, heartbeat, cancellation, bounded explicit resume, atomic completion/checkpoint/continuation and DB-only publication hook |
| `checkpoints.py` | Trusted tenant/run/requester-bound completed-node reads and bounded history; no generic framework saver or serializer |
| `budgets.py` | Step 4-compatible committed request/token reservations and receipts, persistent format-repair allowance and endpoint/model pins |
| `outbox.py`, `dispatch.py` | Claimed/publishing/published/retry/dead publication, stable delivery IDs, bounded backoff, fenced publisher acknowledgments, scoped reconciliation, ID-only Celery publication without implicit retries and duplicate handling |
| `runner.py` | One bounded node per task, heartbeat monitor, cancellation of in-flight work, current checks and sanitized failure states; disabled by default |
| `runtime.py`, `worker_runtime.py`, `connection_tests.py` | Trusted SQL job-to-scope routing with run/job/requester/delivery cross-checks, bounded scoped reconciliation, fail-closed task composition and document-free synthetic connection tests |
| `backend/app/worker.py`, `backend/app/core/config.py` | Disabled-by-default `agentic_summary_enabled`; new ID-only tasks; conditionally add work to the existing Beat schedule and set worker concurrency one |
| `backend/app/models/agent_workflows.py`, `agent_validation.py` | Separate mutable execution ledger, delivery fencing token, orchestration artifact validation and monotonic ORM guards |
| `backend/migrations/versions/b7e31d95a204_add_durable_agent_execution.py` | Narrow additive migration from actual head `f8c2a6d903b1`; no previous migration changed |
| `backend/app/services/llm/adapter_types.py`, `base.py`, `capabilities.py` | Async admission/receipt/repair/overrun hooks preserving existing in-process behavior, with a trusted provider-pin validation hook |
| `backend/pyproject.toml` | Reuse already-installed, reviewed LangGraph 1.2.18/checkpoint 4.3.1 pins in the worker extra; no upgrade or install performed |
| `backend/tests/agent_orchestration_fixtures.py`, `test_agent_recovery.py`, `test_agent_outbox.py`, `test_agent_checkpoint_postgres.py` | Synthetic failure/recovery, real adapter over fake transport, atomic publication and opt-in disposable PostgreSQL verification |
| Existing schema/vector/ingestion/lifecycle tests | Update application-head expectations only; frozen Step 2 fixture migration remains at its historical revision |

## Checkpoint integration decision

Adopt **application-owned completed-node checkpoints**, not a general-purpose
`BaseCheckpointSaver` or the SQLite spike wrapper. Each LangGraph invocation runs
one registered node and ends. SQL atomically stores its validated result, next
cursor and continuation. On the next task the controller starts from that cursor;
it never reruns an already committed node. Input hashes bind the pinned workflow
and exact incoming cursor. Mismatched versions, run identities and hashes fail.

This deliberately does not support native LangGraph interrupts, arbitrary state
editing, subgraphs, pending writes, time travel or generic framework state history.
There are no unchecked secondary saver connections. The restricted checkpoint API
raises for generic saver operations; async application reads use the same scoped
transaction boundary. Do not describe this as a qualified general LangGraph
PostgresSaver. PostgreSQL qualification remains required before production adoption.

LangGraph's [persistence documentation](https://docs.langchain.com/oss/python/langgraph/persistence)
was reviewed along with the installed package signatures. No runtime `setup()` or
schema creation is used. No new serializer, pickle, provider SDK or unchecked
network client is introduced.

## Transaction, replay and publication rules

- Creation commits request sequence, job, immutable input, execution ledger and
  initial workflow delivery together. A failure rolls them all back.
- Publication is outside SQL transactions. Run/delivery IDs and a stable delivery
  identity are the only broker arguments. A crash after broker acceptance can
  duplicate delivery; it cannot authorize another node commit.
- Run locks and monotonic fencing tokens serialize current ownership. Completion
  checks lease, source lifecycle/current processing run, membership, connection,
  pinned profile version/endpoint, budgets and request sequence. A final deadline
  check also rejects a DB publication hook that outlives its lease.
- Completion stores immutable typed step/checkpoint records and the next outbox
  row in one transaction. The final hook must be DB-only and use existing scoped
  revision/pointer primitives. No production hook or summary node is registered.
- Draft generation is distinct from approval. The synthetic publication test uses
  the existing revision CAS and proves one active draft under sequential duplicate
  delivery; it is not PostgreSQL concurrent-publication evidence.
- Explicit resume preserves deadlines, pins, completed work, all allowances and
  delivery counts, and is limited to three safe resumes. Cancelled, stale,
  ambiguous, exhausted and terminal-output paths cannot be reset into fresh work.

## Budgets and external-call ambiguity

Every adapter/probe admission hook commits its allowance before outbound I/O.
Calls and token reservations are never refunded. Format repair is limited once
per ledger; graph repair is limited once per graph cursor. Deadline, binding,
allowances, receipts, cursor and resume counts persist across worker invocations.
ORM and PostgreSQL monotonic guards prevent resetting charged allowances/pins.

If a worker disappears after a call reservation but before node completion, that
node is not automatically replayed: it becomes `agent_ambiguous_attempt`. This
conservative rule also covers a recorded response whose node artifact was not
committed. No provider exactly-once or billing guarantee is claimed. An unfinished
reservation remains unknown usage. Step 4 still owns its explicitly bounded
transient/ambiguous retry policy within a live node.

## Integration limits

`SqlWorkerRuntime` resolves server-created job routing metadata, reauthorizes the
current member, binds transaction-local tenant/run scope, and checks the protected
run/job/requester/source relationship and delivery identity. Reconciliation scans
only bounded job metadata and then uses that scoped path; it does not scan protected
workflow tables globally. Tampered routing is denied in synthetic tests. This
requires PostgreSQL/grant/concurrency qualification. No production runtime instance
is installed because actual summary nodes are later work; the task boundary fails
closed until trusted application composition supplies it.

Document-free connection tests can run through the generic synthetic worker path
and Step 4 prober. The existing schema has no durable document-free test-request
ledger. Live worker tests therefore fail with
`agent_connection_test_persistence_unqualified`; a fresh in-memory budget must not
permit paid probe replay after an acks-late task crash. This gap is explicit,
not concealed as successful worker-network qualification. Direct Step 4 opt-in
qualification remains subject to its separate permit and authorization rules.

See [test results](test-results.md) and [remaining inputs](remaining-inputs.md).
