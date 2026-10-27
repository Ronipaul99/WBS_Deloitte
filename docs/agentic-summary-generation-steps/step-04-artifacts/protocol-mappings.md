# Reviewed protocol mappings

Reviewed 2026-10-27 against official primary documentation. Raw HTTP uses the
existing pinned httpcore 1.0.9 transport. No provider SDK or package upgrade was
introduced. Documentation establishes protocol formats, not capabilities of a
particular account, model or masked Mac gateway.

## Implemented dialects

| Boundary | OpenAI Responses | Anthropic Messages | Compatible Chat Completions |
| --- | --- | --- | --- |
| Path beneath approved prefix | `/responses` | `/messages` | `/chat/completions` |
| Authentication scheme | Registered bearer | Registered Anthropic API key plus fixed version header | Registered bearer or gateway API key |
| Instructions | Top-level `instructions`; role messages in `input` | Top-level `system`; user/assistant `messages` | Leading system message and user/assistant `messages` |
| Output ceiling | `max_output_tokens` | `max_tokens` | `max_tokens` default; explicit qualified `max_completion_tokens` option |
| Native JSON schema | `text.format` | `output_config.format` | `response_format.json_schema` |
| Native tools | Flat Responses function definition | `input_schema` tool definition | Nested Chat `function` definition |
| Tool replay | `function_call` / `function_call_output`, original `call_id` | Assistant `tool_use`, then user `tool_result` with original `tool_use_id` | Assistant `tool_calls`, then tool message with original `tool_call_id` |
| Reported usage | `input_tokens`, `output_tokens` | Input plus cache creation/read counts; output count | `prompt_tokens`, `completion_tokens` |
| Truncation | Incomplete/max-output reason; incomplete native items | Max-token/context-window stop reason | `length` |
| Refusal | Refusal content / content filter | Explicit refusal stop reason | Explicit refusal / content filter |

Responses requests explicitly set `store=false` and `stream=false`; no prior
response ID, provider conversation persistence or background job is used. This
does not establish any vendor retention guarantee. All adapters are nonstreaming.
Known reasoning/thinking fields are discarded and never returned, replayed or
written to the attempt ledger. Stateless replay requiring hidden reasoning or
thinking signatures is unsupported and needs separate qualification.

Each protocol must be selected explicitly. The compatible adapter does not assume
the Mac runs Ollama, LM Studio, or every advertised OpenAI feature. An arbitrary
REST masking format is unsupported until separately implemented and reviewed.

## Supported settings and rejection rules

- Model IDs come from the pinned profile. A mismatched returned model is rejected;
  model aliases must be qualified rather than silently substituted. Exact-model
  probes remain inconclusive when the response does not identify its model.
- Sampling is sent only when explicitly requested and the exact profile advertises
  demonstrated support. Anthropic temperature above 1 is rejected; generic contract
  bounds remain unchanged for other adapters. No parameter is silently clamped.
- Native JSON schema is gated by the existing profile capability contract. In
  validated-JSON mode the adapter instructs JSON and validates locally, without
  assuming an unqualified JSON-mode API option.
- Native tools require demonstrated native-tool support. Otherwise the tested
  application JSON-action envelope is used. Neither path executes tools.
- Only the four registered tools may be requested, and only the per-request
  allowlist is exposed. Native IDs, duplicate IDs, arguments, replay results and
  JSON-action IDs are validated before use.
- System instructions must precede non-system messages, and the first non-system
  message must be user input. Unsupported interleaving is rejected rather than
  reordered. Tool-result replay uses the separate typed exchange field.
- Arbitrary headers, SDK settings, top-k, custom executable mappings, provider
  built-in tools, streaming, compression, hidden-thinking replay and automatic
  model/provider fallback are not supported.

## Schema projection and validation

The model output is validated against the existing `OUTPUT_CONTRACTS` registry:
facts, summary content or verification content. No schema supplied by a model or
an arbitrary tenant JSON blob is accepted.

Strict native wire schemas use a documented common subset: closed objects, required
properties, local references, primitive types, enums and unions. Defaults and
unsupported numeric/string/array constraints are omitted from the wire projection;
discriminated unions are projected to ordinary alternatives. The full original
schema is also supplied in bounded instructions. Pydantic retains **all** field
bounds and cross-field checks locally. A native schema/JSON-mode response is never
accepted solely because it is JSON. External schema references are rejected.
Schema property names resembling schema keywords are preserved.

For non-native tools the wire response is an exclusive envelope with `kind`,
`content` and `actions`. Completed content is validated against the requested
output contract; actions become Step 1 `ToolAction` values. Invalid/unknown actions
fail validation and cannot grant scope or tool permissions.

HTTP request IDs are read only from allowlisted, bounded `x-request-id` / `request-id`
headers. Provider response-resource IDs are validated separately and not mislabeled
as HTTP request IDs. When the request header is absent the result ID is unknown.
Refusal/truncation are terminal typed outcomes, with no successful output attached.

## Primary sources

- [OpenAI Responses migration](https://developers.openai.com/api/docs/guides/migrate-to-responses),
  [function calling](https://developers.openai.com/api/docs/guides/function-calling),
  [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
  and [Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).
- [Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs),
  [stop reasons](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons),
  [tool definitions](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools),
  [tool-call handling](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls),
  and [model listing](https://platform.claude.com/docs/en/api/models/list).
- [Ollama compatibility](https://docs.ollama.com/api/openai-compatibility) establishes
  one documented compatible dialect, including `max_tokens`; it is not evidence
  that the user's gateway uses Ollama or supports the same fields.

Some large API-reference pages could not be fetched by the documentation tool;
the fetched official guides and Chat reference above supplied the reviewed mapping.
No SDK or model version was inferred from inaccessible pages.
