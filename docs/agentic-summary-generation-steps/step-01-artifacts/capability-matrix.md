# Sanitized provider capability matrix

No live inference probes were run. Provider names/protocols below are intended
integration contracts, not observed deployment capabilities. No endpoint or API
credential was supplied/read for this task, and no VM changes or access were made.

| Target | Planned protocol | Model/endpoint/auth | Worker reachability | Context/output limits | Native tools / JSON schema | Refusal / truncation | Usage / timeout / latency | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Mac Llama 8B public gateway | Compatible Chat Completions only if confirmed | Unprovided | Not tested | Unknown | Unknown | Unknown | Unknown | Pending |
| OpenAI | Responses | Accessible model/project unselected | Not tested | Unknown | Unknown | Unknown | Unknown | Pending |
| Claude | Anthropic Messages | Unprovided | Not tested | Unknown | Unknown | Unknown | Unknown | Deferred live qualification before enablement |

The three local fake-provider fixtures use the same synthetic model label and
synthetic 8192/2048 limits solely to exercise validation. `qualification` is
`synthetic_fixture` and `enabled` is false. Their equivalent normalized writer
outputs do **not** demonstrate actual wire compatibility, schema/tool support,
throughput or factual accuracy for any provider. Untested capabilities stay unknown.

For each future authorized worker-path synthetic probe, record: exact profile and
qualification versions, timestamp, model identifier, approved endpoint policy reference
(not a key), protocol/auth scheme, worker network-path identifier, tested token
limits, request/response validity, native tool and JSON behavior, refusal handling,
forced short-output truncation, reported versus estimated usage, timeout and latency.
Record an observed error as an error, not an unsupported capability without analysis.
Avoid retaining raw upstream bodies, credentials, or customer document content.

Synthetic probe content can be the checked-in Example Energy Board/8 MW example.
Use the same facts/schema for provider comparisons. Do not send uploaded PDFs.
