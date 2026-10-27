# Remaining Step 4 inputs and verification

Step 4 is **partially complete**. The local tests prove implemented mappings and
failure handling over controlled fake transports, not actual vendor compatibility.

1. Complete [Step 1 provider/worker qualification](../step-01-artifacts/remaining-inputs.md),
   [Step 2 disposable PostgreSQL checks](../step-02-artifacts/remaining-inputs.md), and
   [Step 3 runtime/TLS/security qualification](../step-03-artifacts/remaining-inputs.md).
   No prior pending result was reclassified as successful. The 14 PostgreSQL tests
   were skipped; SQLite does not establish RLS, grants or concurrent revocation.
2. Obtain the actual public Mac gateway's operator-approved HTTPS host/port/path,
   authentication scheme, exact API dialect/model identifier and proposed limits.
   API masking does not establish Chat Completions or native-tool/schema support.
   Unsupported dialects/authentication/streaming must fail closed, not use an
   unchecked HTTP client or weaken destination/TLS policy.
3. Obtain a chosen accessible OpenAI model/project and qualify Claude separately.
   Provision credentials and runtime encryption keys through a secure operator
   channel. Do not put real keys, URLs with credentials, signed URLs or customer
   document content in Git, fixtures, chat or public evidence.
4. Separately authorize small **synthetic-only** live requests with request/token/time
   and cost ceilings and reviewed rate assumptions. Obtain a valid scoped permit;
   run through the actual worker path. No paid or real-provider API call was made
   by this implementation. Do not infer worker reachability from a laptop test.
5. Verify actual request/response fields, strict-schema projection, registered tool
   replay, JSON-action fallback, exact model identity, native refusals/truncation,
   token accounting/cache counts, Retry-After behavior and timeout ambiguity for
   each selected profile. Qualify any stateless reasoning/tool replay limitation;
   never persist hidden thinking as a workaround.
6. Verify the deployed Linux ARM64 Python/httpcore/AnyIO/OpenSSL behavior, real TLS
   certificates, checked-IP dialing and destination metadata, secure credential
   rotation/revocation, response bounds and sanitization. Fake handshakes do not
   establish actual certificate or gateway compatibility.
7. The later model-management/orchestration steps must supply trusted current
   qualification bindings and immutable profile/settings versions, with an approved
   persistence/audit path for observations/fingerprints. Step 4 returns typed
   in-memory records only. Do not construct live qualification from fixture flags,
   a similar model name, model-list success or a new untested endpoint.
8. Confirm exact model tokenizer/context allowances and reserve enough output/schema
   headroom for real requests. Current byte-based admission is explicitly an estimate;
   no 65K fixture context or probe ceiling is a claim about Llama 8B capacity.

No unresolved input authorizes enabling providers or adding Step 5 functionality.
No graph, durable retry/lease loop, outbox worker, production saver, retrieval/tool
executor, summary agent, API route, UI or deployment was implemented here.
