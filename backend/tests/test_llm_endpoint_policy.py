"""All network behavior is simulated, including public IPs and TLS handshakes."""

import asyncio
import json
import logging
import ssl
from dataclasses import replace

import httpcore
import pytest
from agent_schema_fixtures import access, uid
from llm_security_fixtures import (
    SENTINEL,
    FakeAuthorizer,
    FakeBackend,
    FakeResolver,
    endpoint,
    keys,
    wire_response,
)
from llm_security_fixtures import (
    sessions as sessions,
)
from pydantic import SecretStr

from app.services.agents.persistence_types import EndpointPolicyRecord
from app.services.llm.credential_service import CredentialService
from app.services.llm.credentials import CredentialChange
from app.services.llm.endpoint_policy import (
    ApprovedEndpoint,
    EndpointRegistry,
    OperatorPolicy,
    PinnedEndpoint,
    SystemResolver,
    canonical_host,
    public_ip,
    resolve_destination,
)
from app.services.llm.errors import LlmSecurityError, SecurityCode
from app.services.llm.redaction import sensitive_io
from app.services.llm.secure_transport import (
    PinnedNetworkBackend,
    SecureJsonTransport,
    TransportLimits,
)


def transport(*, backend=None, resolver=None, auth=None, limits=None, scheme="bearer"):
    registry, pinned = endpoint(scheme)
    auth = auth or FakeAuthorizer()
    backend = backend or FakeBackend()
    resolver = resolver or FakeResolver()
    client = SecureJsonTransport(
        registry, auth, limits=limits, resolver=resolver, network_backend=backend
    )
    return client, pinned, auth, backend, resolver


async def send(client, pinned, **kwargs):
    return await client.send(
        connection_id=uid(5),
        pinned=pinned,
        url=pinned.base_url + "/v1/probe",
        purpose="test",
        **kwargs,
    )


@pytest.mark.parametrize(
    "suffix",
    [
        "/v10",
        "/v1/../admin",
        "/v1/%2e%2e/admin",
        "/v1/%252e%252e/admin",
        "/v1//admin",
        "/v1\\admin",
        "/v1;admin",
        "/v1?key=value",
        "/v1#fragment",
        "/v1/%2fadmin",
        "/v1/./probe",
        "/v1\r\nHost: evil",
    ],
)
def test_path_confusion_is_rejected(suffix):
    registry, pinned = endpoint()
    with pytest.raises(LlmSecurityError):
        registry.validate(pinned, pinned.base_url + suffix, "test")


@pytest.mark.parametrize(
    "url",
    [
        "http://gateway.example.invalid/v1",
        "https://user:pass@gateway.example.invalid/v1",
        "https://gateway.example.invalid.evil.invalid/v1",
        "https://gateway.example.invalid:444/v1",
        "https://gateway.example.invalid.:443/v1",
        "https://gateway.example.invalid:/v1",
        "https://gateway.example.invalid:0/v1",
        "https://127.0.0.1/v1",
        "https://gateway.example.invalid@evil.invalid/v1",
        "https:///gateway.example.invalid/v1",
    ],
)
def test_only_exact_operator_origin_is_allowed(url):
    registry, pinned = endpoint()
    with pytest.raises(LlmSecurityError):
        registry.validate(pinned, url, "test")


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "127.1",
        "2130706433",
        "0x7f000001",
        "0177.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.0.1",
        "100.64.0.1",
        "169.254.169.254",
        "168.63.129.16",
        "0.0.0.0",
        "224.0.0.1",
        "255.255.255.255",
        "192.0.0.9",
        "::",
        "::1",
        "fc00::1",
        "fe80::1",
        "fe80::1%eth0",
        "ff02::1",
        "::ffff:8.8.8.8",
        "::ffff:127.0.0.1",
        "64:ff9b::808:808",
        "64:ff9b:1::1",
        "2002:0808:0808::1",
        "2001::1",
        "2001:db8::1",
        None,
    ],
)
def test_metadata_private_special_and_ambiguous_ip_variants_are_denied(address):
    with pytest.raises(LlmSecurityError):
        public_ip(address)


def test_tenant_cannot_invent_approval_or_expand_gateway_permissions():
    registry, pinned = endpoint()
    for change in (
        {"approval_id": uid(71)},
        {"path_prefix": "/"},
        {"host": "other.example.invalid"},
    ):
        record = EndpointPolicyRecord(
            host=pinned.approval.host, path_prefix="/v1", approval_id=uid(70)
        )
        with pytest.raises(LlmSecurityError):
            registry.pin(record.model_copy(update=change))
    other = pinned.approval.model_copy(update={"auth_scheme": "gateway_api_key"})
    with pytest.raises(LlmSecurityError):
        registry.validate(PinnedEndpoint(other), pinned.base_url + "/v1", "test")
    assert canonical_host("Gateway.Example.Invalid") == "gateway.example.invalid"
    assert registry.validate(pinned, pinned.base_url + "/v1/sub", "test").endswith("/v1/sub")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answers", [(), ("8.8.8.8", "10.0.0.1"), ("2606:4700:4700::1111", "::1"), ("8.8.8.8",) * 33]
)
async def test_all_dns_answers_must_be_public_before_any_dial(answers):
    client, pinned, _, backend, _ = transport(resolver=FakeResolver(answers))
    with pytest.raises(LlmSecurityError) as error:
        await send(client, pinned)
    assert error.value.code == SecurityCode.DNS_DENIED and not backend.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["discovery", "test", "inference"])
async def test_checked_numeric_dial_tls_original_host_and_registered_auth(purpose, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    monkeypatch.setenv("ALL_PROXY", "http://169.254.169.254")
    client, pinned, auth, backend, resolver = transport()
    response = await client.send(
        connection_id=uid(5),
        pinned=pinned,
        url=pinned.base_url + "/v1/probe",
        purpose=purpose,
        payload={"synthetic": True},
    )
    assert response.data == {"ok": True} and SENTINEL not in repr(response)
    assert resolver.calls == [(pinned.approval.host, 443)]
    assert backend.calls == [("8.8.8.8", 443)]
    context, server_hostname = backend.stream.tls_options
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    assert server_hostname == pinned.approval.host
    wire = b"".join(backend.stream.writes)
    assert b"Host: gateway.example.invalid" in wire
    assert b"authorization: Bearer " + SENTINEL.encode() in wire
    assert auth.prepares == 1 and auth.verifies >= 1 and backend.stream.closed


@pytest.mark.asyncio
async def test_ipv6_dial_and_rebinding_checks_on_every_new_attempt():
    address = "2606:4700:4700::1111"
    resolver = FakeResolver((address,), ("10.0.0.1",))
    backend = FakeBackend(peer=(address, 443, 0, 0))
    client, pinned, _, _, _ = transport(backend=backend, resolver=resolver)
    await send(client, pinned)
    with pytest.raises(LlmSecurityError):
        await send(client, pinned)
    assert backend.calls == [(address, 443)] and len(resolver.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options",
    [
        {"peer": ("1.1.1.1", 443)},
        {"peer": None},
        {"peer": ("8.8.8.8", 444)},
        {"tls": False},
    ],
)
async def test_unsupported_peer_or_tls_metadata_fails_closed_before_credentials(options):
    backend = FakeBackend(**options)
    client, pinned, _, _, _ = transport(backend=backend)
    with pytest.raises(LlmSecurityError) as error:
        await send(client, pinned)
    assert error.value.code == SecurityCode.DESTINATION_DENIED
    assert not backend.stream.writes and backend.stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["disable", "rotate"])
async def test_authorization_changes_during_tls_block_write_and_no_automatic_retry(mutation):
    auth = FakeAuthorizer()

    async def change():
        if mutation == "disable":
            auth.enabled = False
        else:
            auth.version += 1

    backend = FakeBackend(on_tls=change)
    client, pinned, _, _, _ = transport(backend=backend, auth=auth)
    with pytest.raises(LlmSecurityError):
        await send(client, pinned)
    assert not backend.stream.writes and auth.prepares == 1 and len(backend.calls) == 1
    if mutation == "disable":
        with pytest.raises(LlmSecurityError):
            await send(client, pinned)
        assert len(backend.calls) == 1
    else:
        next_client, pinned, _, _, _ = transport(auth=auth)
        result = await send(next_client, pinned)
        assert result.receipt.credential_version == 2 and auth.prepares == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["disable", "rotate", "clear"])
async def test_real_scoped_service_rechecks_database_before_wire_write(sessions, action):
    registry, pinned = endpoint()
    service = CredentialService(sessions, access(), keys(), registry)
    await service.update(uid(5), CredentialChange(action="replace", secret=SecretStr(SENTINEL)))

    async def change():
        await service.update(uid(5), CredentialChange(action=action))

    backend = FakeBackend(on_tls=change)
    client = SecureJsonTransport(
        registry, service, resolver=FakeResolver(), network_backend=backend
    )
    with pytest.raises(LlmSecurityError):
        await send(client, pinned)
    assert not backend.stream.writes
    if action == "rotate":
        client = SecureJsonTransport(
            registry, service, resolver=FakeResolver(), network_backend=FakeBackend()
        )
        assert (await send(client, pinned)).receipt.credential_version == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [
        "Host",
        "Authorization",
        "Proxy-Authorization",
        "X-Forwarded-For",
        "Forwarded",
        "X-API-Key",
        "Cookie",
        "Content-Length",
        "X-Custom",
    ],
)
async def test_arbitrary_header_injection_is_denied_before_authorization(name):
    client, pinned, auth, backend, _ = transport()
    with pytest.raises(LlmSecurityError):
        await send(client, pinned, advanced_headers=((name, "injected\r\nHost: evil"),))
    assert not backend.calls and auth.prepares == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("scheme", ["anthropic_api_key", "gateway_api_key"])
async def test_registered_api_key_schemes_only(scheme):
    client, pinned, _, backend, _ = transport(scheme=scheme)
    headers = (("anthropic-version", "2023-06-01"),) if scheme == "anthropic_api_key" else ()
    await send(client, pinned, advanced_headers=headers)
    wire = b"".join(backend.stream.writes)
    assert b"x-api-key: " + SENTINEL.encode() in wire
    assert b"authorization:" not in wire


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code",
    [
        (b"302 Found", SecurityCode.ENDPOINT_DENIED),
        (b"401 Unauthorized", SecurityCode.UPSTREAM_FAILED),
    ],
)
async def test_redirects_and_error_bodies_are_not_followed_or_exposed(status, code):
    backend = FakeBackend(
        wire_response(
            SENTINEL.encode(), status=status, headers=((b"Location", b"http://169.254.169.254/"),)
        )
    )
    client, pinned, _, _, _ = transport(backend=backend)
    with pytest.raises(LlmSecurityError) as error:
        await send(client, pinned)
    assert error.value.code == code and error.value.__context__ is None
    assert SENTINEL not in str(error.value) + repr(error.value.public())
    assert len(backend.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        wire_response(b'{"size":"' + b"x" * 200 + b'"}'),
        b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{"size":"' + b"x" * 200 + b'"}',
        wire_response(headers=((b"Content-Encoding", b"gzip"),)),
        b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: 0\r\n\r\n",
        wire_response(b'{"duplicate":1,"duplicate":2}'),
        wire_response(b'{"bad":NaN}'),
        wire_response(b'{"bad":1e999}'),
        wire_response(b"not-json"),
        wire_response(b'"scalar"'),
        wire_response(json.dumps({"key": SENTINEL}).encode()),
    ],
    ids=[
        "length",
        "stream",
        "compression",
        "sse",
        "duplicate",
        "nan",
        "infinity",
        "bad-json",
        "scalar",
        "reflection",
    ],
)
async def test_bounded_json_only_response_boundary(response):
    client, pinned, _, _, _ = transport(
        backend=FakeBackend(response), limits=TransportLimits(response_bytes=100)
    )
    with pytest.raises(LlmSecurityError):
        await send(client, pinned)


@pytest.mark.asyncio
async def test_escaped_secret_reflection_is_blocked_in_decoded_json():
    auth = FakeAuthorizer()
    original = auth.prepare
    secret = 'synthetic-"quoted\\credential'

    async def prepare(*args):
        return replace(await original(*args), secret=SecretStr(secret))

    auth.prepare = prepare
    client, pinned, _, _, _ = transport(
        auth=auth, backend=FakeBackend(wire_response(json.dumps({"nested": [secret]}).encode()))
    )
    with pytest.raises(LlmSecurityError) as error:
        await send(client, pinned)
    assert error.value.code == SecurityCode.RESPONSE_REJECTED


@pytest.mark.asyncio
async def test_oversized_request_and_total_timeout_are_bounded():
    client, pinned, auth, backend, _ = transport(limits=TransportLimits(request_bytes=10))
    with pytest.raises(LlmSecurityError):
        await send(client, pinned, payload={"large": "x" * 100})
    assert not backend.calls and auth.prepares == 0

    class SlowResolver:
        async def resolve(self, host, port):
            await asyncio.sleep(1)

    client, pinned, _, _, _ = transport(
        resolver=SlowResolver(), limits=TransportLimits(total_seconds=0.01)
    )
    with pytest.raises(LlmSecurityError) as error:
        await send(client, pinned)
    assert error.value.code == SecurityCode.TIMEOUT


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["connect", "read"])
async def test_transport_timeouts_and_debug_diagnostics_are_sanitized(phase, caplog):
    backend = FakeBackend(wire_response(headers=((b"X-Echo", SENTINEL.encode()),)))

    async def fail(*args, **kwargs):
        logging.getLogger("httpcore.connection").debug(
            "key=%s", SENTINEL, extra={"raw_key": SENTINEL}
        )
        raise httpcore.ReadTimeout(SENTINEL)

    if phase == "connect":
        backend.connect_tcp = fail
    else:
        backend.stream.read = fail
    client, pinned, _, _, _ = transport(backend=backend)
    with caplog.at_level(logging.DEBUG), pytest.raises(LlmSecurityError) as error:
        await send(client, pinned)
    assert error.value.code == SecurityCode.TIMEOUT and error.value.__context__ is None
    assert SENTINEL not in caplog.text + str(error.value)
    assert all(SENTINEL not in repr(record.__dict__) for record in caplog.records)


def test_redaction_is_context_local_and_drops_exception_and_extra_fields(caplog):
    logger = logging.getLogger("httpcore.http11")
    with caplog.at_level(logging.DEBUG):
        with sensitive_io():
            logger.debug(SENTINEL, extra={"credential": SENTINEL}, exc_info=ValueError(SENTINEL))
        logger.debug("ordinary diagnostic outside secure transport")
    assert SENTINEL not in caplog.text + repr([record.__dict__ for record in caplog.records])
    assert "ordinary diagnostic outside secure transport" in caplog.text


@pytest.mark.asyncio
async def test_numeric_public_gateway_policy_and_ipv6_literal_normalization():
    approval = ApprovedEndpoint(
        approval_id=uid(70), host="2606:4700:4700::1111", path_prefix="/v1", auth_scheme="bearer"
    )
    registry = EndpointRegistry(OperatorPolicy(endpoints=(approval,)))
    pinned = registry.pin(
        EndpointPolicyRecord(host=approval.host, path_prefix="/v1", approval_id=uid(70))
    )
    assert (
        registry.validate(pinned, "https://[2606:4700:4700::1111]/v1", "test")
        == pinned.base_url + "/v1"
    )
    assert await resolve_destination(pinned, FakeResolver((approval.host,)), 1) == approval.host


@pytest.mark.asyncio
async def test_system_resolver_deduplicates_without_real_dns(monkeypatch):
    async def lookup(*args, **kwargs):
        return [(2, 1, 6, "", ("8.8.8.8", 443)), (2, 1, 6, "", ("8.8.8.8", 443))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    assert await SystemResolver().resolve("synthetic.example.invalid", 443) == ("8.8.8.8",)


@pytest.mark.asyncio
async def test_wrong_host_unix_socket_and_unsafe_tls_context_fail_closed():
    _, pinned = endpoint()

    async def authorize():
        pass

    raw = FakeBackend()
    backend = PinnedNetworkBackend(pinned, "8.8.8.8", authorize, 100000, raw)
    with pytest.raises(LlmSecurityError):
        await backend.connect_tcp("unapproved.example.invalid", 443)
    with pytest.raises(LlmSecurityError):
        await backend.connect_unix_socket("/var/run/test")
    stream = await backend.connect_tcp(pinned.approval.host, 443)
    unsafe = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    unsafe.check_hostname = False
    unsafe.verify_mode = ssl.CERT_NONE
    with pytest.raises(LlmSecurityError):
        await stream.start_tls(unsafe, pinned.approval.host)
    assert not raw.stream.writes


@pytest.mark.parametrize(
    "raw", [None, "{}", "not-json", '{"endpoints":[]}', '{"endpoints":[],"endpoints":[]}']
)
def test_operator_policy_is_required_bounded_and_rejects_duplicate_fields(raw):
    with pytest.raises(LlmSecurityError):
        EndpointRegistry.parse(SecretStr(raw) if raw else None)


@pytest.mark.asyncio
async def test_synthetic_mac_gateway_approval_is_scoped_to_host_port_path_and_purpose():
    approval = ApprovedEndpoint(
        approval_id=uid(70),
        host="mac-demo.example.invalid",
        port=8443,
        path_prefix="/masked/api",
        auth_scheme="gateway_api_key",
        purposes=("test",),
    )
    registry = EndpointRegistry(OperatorPolicy(endpoints=(approval,)))
    pinned = registry.pin(
        EndpointPolicyRecord(
            host=approval.host, port=8443, path_prefix="/masked/api", approval_id=uid(70)
        )
    )
    backend = FakeBackend(peer=("8.8.8.8", 8443))
    client = SecureJsonTransport(
        registry, FakeAuthorizer(), resolver=FakeResolver(), network_backend=backend
    )
    result = await client.send(
        connection_id=uid(5),
        pinned=pinned,
        url=pinned.base_url + "/masked/api/probe",
        purpose="test",
    )
    assert result.status == 200 and backend.calls == [("8.8.8.8", 8443)]
    for url, purpose in (
        ("https://other.example.invalid:8443/masked/api/probe", "test"),
        (pinned.base_url + "/masked/api/probe", "inference"),
        (pinned.base_url + "/outside", "test"),
    ):
        with pytest.raises(LlmSecurityError):
            await client.send(connection_id=uid(5), pinned=pinned, url=url, purpose=purpose)
    assert len(backend.calls) == 1


@pytest.mark.asyncio
async def test_chunked_overflow_and_oversized_headers_are_rejected():
    body = b'"' + b"x" * 100 + b'"'
    chunked = (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
        + hex(len(body))[2:].encode()
        + b"\r\n"
        + body
        + b"\r\n0\r\n\r\n"
    )
    oversized_headers = wire_response(headers=((b"X-Large", b"x" * 17000),))
    for response in (chunked, oversized_headers):
        client, pinned, _, _, _ = transport(
            backend=FakeBackend(response), limits=TransportLimits(response_bytes=50)
        )
        with pytest.raises(LlmSecurityError):
            await send(client, pinned)


@pytest.mark.asyncio
async def test_success_diagnostics_cannot_echo_response_header_secrets(caplog):
    client, pinned, _, _, _ = transport(
        backend=FakeBackend(wire_response(headers=((b"X-Echo", SENTINEL.encode()),)))
    )
    with caplog.at_level(logging.DEBUG):
        await send(client, pinned)
    assert SENTINEL not in caplog.text + repr([item.__dict__ for item in caplog.records])


@pytest.mark.asyncio
async def test_cancellation_is_not_converted_to_a_retryable_error():
    backend = FakeBackend()

    async def cancel(*args, **kwargs):
        raise asyncio.CancelledError()

    backend.connect_tcp = cancel
    client, pinned, _, _, _ = transport(backend=backend)
    with pytest.raises(asyncio.CancelledError):
        await send(client, pinned)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["tls-error", "cancelled", "total-timeout"])
async def test_tls_setup_failure_or_cancellation_always_closes_the_unowned_stream(failure):
    async def fail():
        if failure == "tls-error":
            raise ssl.SSLCertVerificationError(SENTINEL)
        if failure == "cancelled":
            raise asyncio.CancelledError()
        await asyncio.sleep(1)

    backend = FakeBackend(on_tls=fail)
    client, pinned, _, _, _ = transport(backend=backend, limits=TransportLimits(total_seconds=0.05))
    expected = asyncio.CancelledError if failure == "cancelled" else LlmSecurityError
    with pytest.raises(expected) as error:
        await send(client, pinned)
    assert backend.stream.closed and not backend.stream.writes
    assert SENTINEL not in str(error.value)
