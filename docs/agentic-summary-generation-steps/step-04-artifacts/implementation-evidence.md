# Step 4 implementation evidence

Date: 2026-10-27. Status: **independent local implementation verified; not fully
complete**. Live provider/worker qualification and pending Step 1-3 verification
remain open. No provider, connection or model profile was enabled.

## Files and responsibilities

| File | Change and purpose |
| --- | --- |
| `backend/app/services/llm/base.py` | Implements the existing structural `GenerationProvider.generate` interface with qualified-profile binding, shared budget admission, bounded retries/repair and Pydantic output validation |
| `backend/app/services/llm/openai_provider.py` | Explicit stateless Responses request/response, function replay, refusal/truncation and usage mappings |
| `backend/app/services/llm/anthropic_provider.py` | Explicit Messages mapping, version header, native tools/results and cache-inclusive usage |
| `backend/app/services/llm/compatible_provider.py` | Explicit Chat Completions mapping with a qualification-bound token-limit dialect |
| `backend/app/services/llm/registry.py` | Closed provider/protocol registry; no arbitrary imports or fallback |
| `backend/app/services/llm/protocol_support.py` | Registered tool schemas, bounded JSON parsing, strict wire-schema projection, JSON-action envelope and local output validation |
| `backend/app/services/llm/adapter_types.py` | Typed qualification references and attempt metadata; caller-owned in-process call/token/deadline/repair budget |
| `backend/app/services/llm/capabilities.py` | Opt-in synthetic probes, settings/provenance/invalidation records, bounded one-page model listing and explicit live-probe admission limits |
| `backend/tests/llm_adapter_fixtures.py` | Synthetic protocol fixtures and multi-attempt in-memory HTTP wire backend |
| `backend/tests/test_llm_adapters.py`, `test_llm_capabilities.py` | 197 new adapter/probe/security/budget tests |
| Step 4 document, implementation index and this artifact directory | Actual status, compatibility decisions, verification and outstanding gates |

There are no new dependencies, SDKs, persistence models, migrations, routes, UI
components, workflow nodes, production checkpointers or worker tasks. Adapters are
not connected to the existing summary-generation placeholder or application startup.
LangGraph + Pydantic decisions and the existing ingestion/vector implementation
are preserved.

## Minimal prerequisite compatibility changes

1. `backend/app/services/llm/contracts.py`: add optional bounded `tool_results`
   containing typed completed `ToolExchange` records, plus optional sanitized
   `provider_request_id` on `GenerationResult`. This is needed because the Step 1
   interface could request tools but could not represent their results or provider
   request correlation. Old requests/results still validate with the defaults.
   Tool replay has a four-exchange ceiling, unique IDs, allowlist validation and
   bounded JSON-object output. No tool executor was added.
2. `backend/tests/agent_contract_fixtures/schemas.json`: refresh only the
   `GenerationRequest` and `GenerationResult` schema entries. Other schema entries
   remain semantically identical. `provider-requests.json` adds only the new empty
   `tool_results` default to the three generated request fixtures. No synthetic
   provider was relabeled live or enabled.
3. `backend/app/services/llm/secure_transport.py`: retain policy/TLS/peer enforcement
   while adding controlled HTTP status, bounded Retry-After, allowlisted HTTP
   request IDs, current credential receipt and conservative submission metadata.
   `TransportFailure` remains a `LlmSecurityError`; `public()` still returns only
   code/correlation. Error bodies are never parsed. Optional tighter per-attempt
   timeout and expected-tenant checks support adapter budgets and profile scope.
   Known current-key material in an outbound payload is rejected before DNS/dialing.
   Synthetic/injected transport origin is explicitly distinguished from real network
   operation. These additions avoid a second, unchecked HTTP path.

No Step 2 model, repository, permission or migration was changed. Step 1/2 artifact
documents and Step 3 artifact documents remain historical evidence, not new live
qualification. No actual key ring, credential or environment file was changed.

## Exit-criterion assessment

| Criterion | Evidence and limit |
| --- | --- |
| Same typed task across adapters | Three output contracts validated across all three adapters over fake HTTP wire responses; real-provider equivalence pending |
| Actual public Mac gateway capability results | **Pending**; hostname/protocol/model/limits/auth and explicit worker-path authorization are still needed |
| Unsupported options rejected / JSON-action path | Local tests cover capability gates, protocol/auth/profile mismatches, registered native tools, JSON action allowlists and strict local validation |
| Bounded retry/repair/error and accurate provenance | Shared admission limits, one repair total, no retry of that repair, conservative unknown usage, versioned receipts and sanitized errors tested locally |

See [protocol mappings](protocol-mappings.md), [budgets and qualification](qualification-and-budgets.md),
[test results](test-results.md) and [remaining inputs](remaining-inputs.md).

Nothing was deployed, committed or pushed. No `.env`, actual credential, Docker,
Nginx, CI, VM, ingestion, retrieval or existing authentication behavior was changed.
No private document was read or sent to a provider. Official documentation was
retrieved; all inference/discovery/probe executions used synthetic fake transports.
