# Step 1 implementation evidence

Status: local implementation verified; **not fully complete**. Live Mac/OpenAI
qualification and production PostgreSQL checkpoint isolation remain pending.
Execution date: 2026-10-27. Inputs and tests are synthetic; no private PDF was read.

## Implemented files and purpose

- `backend/app/services/llm/contracts.py`: versioned immutable inference contracts,
  explicit provider/protocol pairing, observed/unknown capabilities, bounded requests,
  safe failure codes, usage provenance, allowlisted tool arguments, result correlation,
  refusal/truncation separation, and an async provider Protocol without an adapter.
- `backend/app/services/agents/contracts.py`: pinned workflow/source scope, evidence
  locators, facts/requirements, complete tender categories, source-reading coverage,
  verification/review artifacts, and pure role/transition assertions.
- `__init__.py` in those two directories: package descriptions only.
- `backend/tests/test_agent_contracts.py`: valid/invalid boundaries and fake providers.
- `backend/tests/agent_contract_fixtures/build_fixtures.py`, `summary.json`,
  `provider-requests.json`, `schemas.json`: deterministic synthetic fixtures and
  Pydantic JSON Schema snapshots, including separate model-writable output schemas.
- `backend/tests/agent_contract_fixtures/checkpointer_spike.py` and
  `backend/tests/test_agent_checkpointer_spike.py`: an isolated real LangGraph graph,
  SQLite interruption/restart/replay tests, scope guards, and a raw-saver negative control.
- `backend/pyproject.toml`: a separate `agent-qualification` optional dependency group.
  Installed locally: LangGraph 1.2.18, langgraph-checkpoint 4.3.1,
  langgraph-checkpoint-sqlite 3.1.2. Existing Pydantic 2.14.1 remains unchanged.
- Step 1 document/index and this artifacts directory: actual status, contract decisions,
  test results, capability matrix, checkpointer limitations, and external input checklist.

LangGraph handles the synthetic graph; Pydantic validates exchanged data, following
the user's explicit selection. Neither library is wired into existing app behavior.
No LLM SDK, provider adapter, connection lookup, summary agent, application route,
UI, database migration, or production checkpoint persistence was added.

## Exit criteria evidence

| Criterion | Evidence/status |
| --- | --- |
| Typed full-path contracts and bounded fixtures | Implemented; schema snapshots and contract tests pass |
| Agent roles/transitions with one repair | Contract assertions and [contract decisions](contracts-and-transitions.md); not a running workflow |
| Checkpointer recovery/isolation evidence or unresolved design | Local process recovery and guard tests pass; raw saver isolation fails by design; PostgreSQL decision unresolved |
| Live Mac/OpenAI capabilities before enablement | **Pending**, no live profiles enabled |
| Missing inputs explicit; no invented capability | [Capability matrix](capability-matrix.md), [remaining inputs](remaining-inputs.md); fixtures explicitly synthetic and disabled |

See [test results](test-results.md) for commands and the test-setup isolation caveat.
Existing unrelated checkout changes were preserved. No environment files, credentials,
Docker/Nginx files, CI workflows, production data, or VM services were changed.

## Deliberate limits

These are data contracts, not authorization, extraction, or verification services.
They check identity equality, reference integrity, range arithmetic, and bounded
artifacts. They do not query document permissions or processing state, validate
quotes/hashes against real chunks, prove semantic entailment, enforce accumulated
runtime token budgets, or approve human revisions. Those are later-step work.
No claim of production PostgreSQL RLS or exactly-once provider billing is made.
