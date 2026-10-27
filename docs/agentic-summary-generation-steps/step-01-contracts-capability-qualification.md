# Step 1: Define contracts and qualify integration choices

Status: local contracts and LangGraph spike implemented; external qualification pending.
Evidence: [Step 1 artifacts](step-01-artifacts/implementation-evidence.md).
Depends on the [master plan](../agentic-summary-generation-plan.md).
Next: [Step 2](step-02-persistence-permissions.md).

## Objective

Agree on the data exchanged by agents, providers, persistence, and the UI before
building provider-specific behavior. Prove the Mac gateway and graph persistence
approach rather than infer capabilities from a product name.

## Implementation tasks

1. Define Pydantic contracts for `WorkflowInput`, `ModelProfileSnapshot`,
   `ProviderCapabilities`, `GenerationRequest`, `GenerationResult`, `ToolAction`,
   `EvidenceReference`, `Fact`, `Requirement`, `TenderSummary`, `CoverageReport`,
   and `VerificationReport`. Include schema versions and bounded strings/arrays.
2. `WorkflowInput` binds tenant/project/document, completed processing-run ID,
   source hash, requester, profile version, and workflow/prompt/schema versions.
   IDs that authorize access are supplied by application code, never by the model.
3. Define evidence as canonical chunk ID/hash, physical page(s), heading path,
   exact quote, character range, and optional table/row identity. Character ranges
   use Unicode code-point offsets with inclusive start/exclusive end; UI highlighting
   must not confuse these with JavaScript UTF-16 indices.
4. Separate provider protocol from model identity. Specify native Responses,
   Anthropic Messages, and compatible Chat Completions adapters; arbitrary REST
   formats require another registered adapter.
5. Define concise failure codes for configuration, unavailable provider, context
   overflow, refusal, invalid schema, budget exhaustion, stale/deleting input,
   cancellation, and evidence verification. Never return raw upstream errors.
6. Define required tender categories and critical fact classes: issuer, capacity/
   unit counts, eligibility, dates, financial values, EMD/PBG, and conditional rules.
   Unknown, conflicting, and unsupported are distinct outcomes.
7. Build a small fake-provider contract harness and JSON-schema fixtures. Probe
   the proposed LangGraph checkpointer with an interrupted graph and two tenants;
   document how every checkpoint transaction enforces tenant/run scope and replay.
8. Collect the Mac gateway URL, protocol/auth scheme, exact Llama model ID, verified
   context/output limits, and availability. Run an explicitly authorized synthetic
   extraction through the worker's network path. Record native-tool/JSON support,
   truncation behavior, usage availability, timeout, and latency. No private PDF is
   needed for this probe. Repeat a minimal equivalent check for the chosen OpenAI
   model. Claude must later pass its own adapter/qualification checks before enablement.

## Proposed implementation targets

- `backend/app/services/agents/contracts.py` and `llm/contracts.py`.
- `backend/tests/test_agent_contracts.py` and provider contract fixtures.
- A sanitized capability matrix and a checkpointer decision record in this step's
  evidence folder. Pin actual package versions during implementation.

## Verification

Test missing scope/version fields, oversized payloads, invalid page/range values,
unknown tool names, refusal/truncated outputs, and equivalent normalized results
from provider fixtures. Assert secrets cannot be serialized into workflow input.
For the persistence spike, interrupt/restart a graph and attempt cross-tenant
checkpoint access; a random thread ID alone must not grant access.

After adding the tests, run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -e ".[dev,agent-qualification]"
.\.venv\Scripts\python.exe -m pytest --noconftest tests/test_agent_contracts.py tests/test_agent_checkpointer_spike.py -q
```

Use `--noconftest` for these isolated tests: the existing root test setup imports
the application and deletes `backend/.test-data` at session end. These tests use
only synthetic fixtures and disposable SQLite files; that shared setup is unnecessary.
The qualification extra is local/test-only; production worker packaging is deferred.

## Exit criteria

- [x] Contracts cover the full summary/review path and have bounded valid fixtures.
- [x] Agent roles and legal transitions are documented, including one repair pass.
- [x] Checkpointer isolation/recovery has evidence or a clearly recorded unresolved design.
- [ ] Actual Mac/OpenAI capability results are recorded before their profiles are enabled.
- [x] Missing external inputs remain explicitly pending; no unsupported capability is advertised.

The checkpointer checkbox records a successful local recovery/guard spike and an
explicitly unresolved PostgreSQL isolation design. It does not approve production
adoption. Step 1 is not fully complete until required live qualification is recorded.

Reference: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs),
[Ollama compatibility](https://docs.ollama.com/api/openai-compatibility), and
[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence).
