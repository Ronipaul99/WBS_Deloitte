# Step 4: Implement provider adapters and capability tests

Status: independent local implementation verified, live qualification pending,
2026-10-27. **Not fully complete**. Depends on Steps 1-3; their pending verification
remains open. See [implementation evidence](step-04-artifacts/implementation-evidence.md)
and [remaining inputs](step-04-artifacts/remaining-inputs.md).
Previous: [Step 3](step-03-credentials-endpoint-security.md).
Next: [Step 5](step-05-durable-orchestration.md).

## Objective

Run the same typed extraction/writing/verifying requests through OpenAI, Claude,
and an approved compatible gateway, with provider differences isolated in adapters.

## Implementation tasks

1. Implement the application-owned provider interface from Step 1. Requests carry
   bounded role instructions, evidence, allowed tool schemas, output schema, and
   verified model settings; results normalize content/actions, stop reason, usage,
   provider request ID, refusal, and truncation. Secret resolution stays outside
   model-visible input and serialized requests/checkpoints.
2. Implement OpenAI Responses, Anthropic Messages, and compatible Chat Completions
   adapters. Pin reviewed dependencies if SDKs are added. Keep a raw HTTP adapter
   only where its format and error handling are explicitly implemented and tested.
3. Map provider-native token limits, system-message formats, schema settings,
   tool-call IDs/results, and supported sampling controls. Reject unsupported
   options rather than silently ignoring user configuration.
4. Normalize native tool calls and schema-based `ToolAction` responses to one
   validated application action. A small Llama model can use a JSON action envelope
   when native tool support is unreliable. Only registered tools can execute.
5. Validate all results with Pydantic. A JSON-mode response is not assumed to match
   the schema. Permit one format-repair request within the total run budget, never
   an unbounded JSON repair loop. Refusals and truncation are explicit failures/results.
6. Implement capability probes using synthetic text: authentication/reachability,
   exact model access, output format, optional tool use, token-limit handling,
   usage metadata and timeouts. List models only when supported; manual model IDs
   are allowed. Model-list failure is not proof that inference is unavailable.
7. Record capability test time and connection/profile version. Changing endpoint,
   model, or relevant settings invalidates the old test result. Do not enable a
   capability because another model/server with a similar name supports it.
8. Bound transient retries and error bodies. Record unknown usage after ambiguous
   timeouts; do not claim exactly-once billing. No automatic Mac-to-cloud fallback.

## Proposed implementation targets

- `backend/app/services/llm/base.py`, `openai_provider.py`, `anthropic_provider.py`,
  `compatible_provider.py`, `capabilities.py`, and a provider registry.
- Provider dependencies/constraints and worker packaging, if needed.
- `test_llm_adapters.py` and sanitized protocol fixtures.

## Verification

Use fake HTTP transports for successful schema output, tool actions, HTTP 401/403,
429/retry-after, transient failures, timeout-after-submit, oversized bodies,
refusal, missing usage, malformed JSON, truncated output, and unsupported settings.
Assert protocol-specific payloads and normalized results. Ensure the adapter never
forwards keys into prompts or redirects them to another host.

Run explicitly authorized small live tests for the real Mac gateway and chosen
OpenAI model outside normal CI. Qualify Claude separately before its connection is
enabled. Do not run paid network calls as an implicit unit-test dependency.

## Exit criteria

- [ ] The same typed task has equivalent application-level results across adapters.
- [ ] Public Mac gateway capability results describe that actual endpoint/model.
- [ ] Unsupported features are rejected or use the tested JSON-action path.
- [ ] Retry/repair/error behavior is bounded and preserves accurate usage/provenance.

Local evidence: 197 new Step 4 tests cover all three adapters and capability
primitives. The combined Step 1-4 regression run passed 708 tests, with 14
PostgreSQL tests skipped. The checkboxes remain open for overall sign-off because
actual Mac/OpenAI/Claude, worker-path and prerequisite qualification is pending.

References: [OpenAI Responses](https://developers.openai.com/api/reference/responses/overview),
[Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs),
and [Ollama compatibility](https://docs.ollama.com/api/openai-compatibility).
