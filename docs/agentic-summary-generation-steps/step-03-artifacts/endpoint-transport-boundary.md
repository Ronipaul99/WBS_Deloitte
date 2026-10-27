# Endpoint policy and outbound transport boundary

## Ownership and enforcement

The operator supplies an immutable `OperatorPolicy` at runtime, not through a
tenant request. Each approval names exact canonical HTTPS host, port, path-prefix
segment boundary, registered authentication scheme, and allowed purposes. Tenant
administrators select `approval_id`; their persisted host/port/prefix must match.
They cannot add operator approvals, change the scheme or allow internal networks.
Changing policy requires replacing the operator-owned registry in the application
process; future secret/config reload orchestration is outside this step.

All discovery, connection-test and inference consumers must eventually use
`SecureJsonTransport.send`. None of these consumers/adapters are implemented here.
Calling a different HTTP library would bypass this boundary and is prohibited for
future adapters. Resolver/backend dependency injection is trusted code for tests,
never tenant configuration or a request parameter.

The enforced sequence is:

1. Revalidate the pinned approval, purpose, normalized origin, port and path. Reject
   embedded credentials, HTTP, fragments, queries, percent encoding, backslashes,
   dot segments, repeated slashes and prefix lookalikes. Unsupported URL forms fail
   closed instead of relying on different gateway/proxy normalization behavior.
2. Validate the method, fixed registered headers and serialized JSON request bound.
   Authorize current scoped credential in a fresh short DB transaction.
3. Resolve with a timeout; require 1-32 answers and validate **every** IPv4/IPv6
   answer. Reject private, link-local/metadata, loopback, unspecified, reserved,
   multicast, carrier-NAT, IPv4-mapped IPv6, scoped addresses, NAT64, Teredo and
   6to4 transitions. Explicitly block the Azure special-service IP and special
   `192.0.0.0/24` range as well. Alternate numeric host spellings are rejected.
4. Give the underlying AnyIO TCP backend only one validated numeric IP. It does
   not receive the hostname for dialing, eliminating a second unchecked hostname
   lookup. Check actual peer IP **and port** against the chosen address before TLS.
   All answers are checked even though only the first is dialed; no automatic
   retry/failover or connection reuse is implemented.
5. Upgrade with `ssl.create_default_context()`, `CERT_REQUIRED`, hostname checking
   and the original approved host for SNI/identity verification. Recheck actual
   peer and require TLS metadata. Unknown peer/TLS metadata fails closed. IP
   literals retain normal certificate IP-SAN checks. No custom insecure SSL option
   or private-network exception exists.
6. Before each request-byte write, recheck peer and current scoped connection,
   permission and credential version in a new DB transaction. Rotation/revocation
   during DNS/TLS therefore prevents the stale credential from being written.
7. Refuse every redirect. Ignore environment proxy variables by using a direct
   `httpcore.AsyncConnectionPool`, with no proxy or redirect facility. Bound
   response headers/wire/body, accept JSON only, discard error bodies, and reject
   exact API-key reflection in decoded JSON keys/values, including escaped strings.

DNS is resolved again on a later explicit attempt. A changed/mixed unsafe answer
is rejected before any subsequent connection. There is no hostname fallback after
a failed IP dial. A synthetic public Mac gateway approval is tested without an
exception for other destinations. Real Mac hostname, API protocol, path and auth
are still external inputs; nothing contacts or approves that real gateway here.

## Supported operations and bounds

| Boundary | Current behavior |
| --- | --- |
| Protocol | HTTPS, HTTP/1.1, GET/POST, JSON dict request; GET has no body |
| Authentication | Registered `bearer`, `anthropic_api_key`, `gateway_api_key`; credential supplied only by authorized service |
| Advanced headers | Only `anthropic-version: 2023-06-01` for its registered scheme; no generic header bag |
| Prohibited headers | User Host, Authorization, X-API-Key, forwarding, proxy, Cookie, framing and unrelated headers |
| Default timeout | 5s DNS/connect; 60s read/write; 90s total including credential checks |
| Configurable limit | Positive timeouts <=600s; request/response byte limits 1..8 MiB, default 1 MiB |
| Response headers | <=16 KiB after parsing; additional raw-wire ceiling and HTTP parser limits |
| Body | Content-Length precheck plus cumulative streamed bytes; bounded raw-wire reads even for chunked/no-length framing |
| Response format | `application/json`, identity encoding, dict/list, duplicate keys/nonfinite values rejected, nesting <=64 |
| Not supported | SSE, WebSockets, HTTP/2, compression, redirects, proxies, unix sockets, user SSL contexts, query credentials, arbitrary headers/private gateways |

The raw-wire ceiling is twice the configured body limit plus 64 KiB; reads are at
most 64 KiB. It also bounds malformed/chunked framing before a body is available.
Headers and a body can arrive in the same TCP read; an error body is never parsed,
returned, logged or persisted. Future streaming/provider formats require a separate
reviewed bounded implementation, not bypassing policy with another transport.

## Diagnostics and metadata

`LlmSecurityError.public()` returns a fixed code and generated correlation UUID.
Underlying DNS/TLS/parser/SQL exceptions and raw error bodies are not exposed.
Do not export local variables, raw request schemas, raw Pydantic error dictionaries,
`ResolvedCredential`, request headers or arbitrary response bytes to telemetry.

Within the secure transport task context, known httpcore/httpx diagnostic loggers
replace whole records, removing args, traceback and extra fields. Other application
logging behavior is unchanged. No provider SDK, trace callback, prompt transcript,
LangGraph tracing integration, metric label or exporter receives credentials.
An external APM system that captures arbitrary Python locals is not qualified by
these tests and must be disabled/redacted before real-key deployment.

Lifecycle audit records contain actor/tenant/connection/version/key-version/action.
An attempt receipt also identifies purpose, approval and attempt. The corresponding
`llm_call_authorized` audit means authorization admitted an attempt, **not** that
the network call completed successfully. No upstream payload is audited. Existing
authentication behavior, routes and job/checkpoint data are unchanged.

## Qualification limits

Fake streams assert numeric dialing, peer checks, TLS context/SNI and failures;
they do not verify actual certificates or Linux/ARM64 behavior. PostgreSQL row
locks, RLS/grants and production revocation races remain pending. No claim is made
about real gateway, provider, TLS or deployment compatibility.

The design uses public interfaces documented by
[httpcore network backends](https://www.encode.io/httpcore/network-backends/),
[cryptography AESGCM](https://cryptography.io/en/latest/hazmat/primitives/aead/#cryptography.hazmat.primitives.ciphers.aead.AESGCM),
and [Python TLS hostname verification](https://docs.python.org/3/library/ssl.html#ssl.SSLContext.check_hostname).
Installed httpcore/AnyIO source was also inspected for numeric-IP dialing and
`server_addr`/`ssl_object` metadata. Requalify these assumptions before upgrading
the transport dependencies or using a different runtime/backend.
