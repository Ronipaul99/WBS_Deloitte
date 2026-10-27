# Step 1 verification results

Executed locally on 2026-10-27 with Python 3.12.10, Windows 11 AMD64,
Pydantic 2.14.1, LangGraph 1.2.18, langgraph-checkpoint 4.3.1,
langgraph-checkpoint-sqlite 3.1.2, pytest 8.4.2 and Ruff 0.17.0.
No ARM64/worker-path qualification is claimed.

## Targeted tests

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest --noconftest tests/test_agent_contracts.py tests/test_agent_checkpointer_spike.py -q --tb=short
```

Result: **188 passed in 22.51 seconds**, exit code 0.

Coverage includes required source/version assertions; profile tenant/protocol and
qualification boundaries; strict scalar/string/collection bounds; secret-field
exclusion; all four tool contracts and injected-scope rejection; result correlation
and allowed tools; JSON validity versus output-schema validity; refusal/truncation;
honest usage; Unicode evidence offsets and locator bounds; cross-scope evidence;
fact support/decimal values; requirements; coverage partitioning and partial results;
critical findings; draft/reference integrity; model-writable output scope exclusion;
and legal transitions with no second repair. Three fake providers return equivalent
validated writer content; they do not test real provider wire formats.

Real LangGraph tests cover a new-process resume, replay preserving completed work,
two synthetic tenants in a disposable SQLite file, negative raw-saver access,
guarded read/list/write/pending-write/delete/delta/history-cursor operations,
unscoped-list rejection, graph API scope rejection and authorized mutation/deletion.

During development, a reserved pytest fixture name and Windows-hostile oversized
auto-generated test IDs caused harness errors; both were corrected before this
final passing run. An installed saver method's keyword-only signature was also
matched in the test subclass. No failed result is counted as successful evidence.

## Static and dependency checks

```powershell
.\.venv\Scripts\python.exe -m ruff check app/services/agents app/services/llm tests/agent_contract_fixtures tests/test_agent_contracts.py tests/test_agent_checkpointer_spike.py
.\.venv\Scripts\python.exe -m ruff format --check app/services/agents app/services/llm tests/agent_contract_fixtures tests/test_agent_contracts.py tests/test_agent_checkpointer_spike.py
.\.venv\Scripts\python.exe -m pip check
```

Results: **All checks passed**; **8 files already formatted**;
**No broken requirements found**. No existing installed dependency was upgraded by
the LangGraph install; the required new dependency closure was added locally.
Direct qualification packages are pinned in the optional dependency group.

Fixture/schema regeneration uses no application configuration:

```powershell
$env:PYTHONPATH=(Get-Location).Path
.\.venv\Scripts\python.exe tests/agent_contract_fixtures/build_fixtures.py
```

The test asserts generated synthetic fixtures and all 15 contract schema snapshots
match the checked-in JSON. Provider-specific strict-schema conversion is not tested.

## Isolation and final diff review

The existing `tests/conftest.py` imports the application, resets a test database and
recursively deletes `backend/.test-data` at session end. These standalone tests
were deliberately run with `--noconftest`; that setup was not loaded or changed.
Tests use synthetic inputs and pytest temporary directories. The broader application
suite was not run because it is outside this change and risks existing user uploads.

A SHA-256 comparison against the starting 390-file nonignored checkout snapshot
found only Step 1 package/test/fixture/artifact files, `backend/pyproject.toml`, the
Step 1 document and implementation index changed/added; no baseline file deleted.
Pre-existing UI/deployment/master-plan/later-step documents remain byte-identical.
`git diff --check -- backend/pyproject.toml` passed. New text files were also checked
for trailing whitespace. No production app imports either new package, and no
application file imports LangGraph; only the isolated test harness does.

Ignored environment/credential files were not edited. No VM, CI, Docker, Nginx,
production database, live provider, route, UI, deployment, commit or push was involved.

## Not run / still pending

- Actual Mac/OpenAI worker-path capability and latency probes; Claude qualification.
- Production PostgreSQL checkpointer/RLS, concurrent transaction and worker recovery tests.
- End-to-end summary generation, source entailment/evaluation, ARM64 packaging or deployment.

These are not reported as passes. See [remaining inputs](remaining-inputs.md).
