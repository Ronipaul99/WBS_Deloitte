"""Bounded HTTPS JSON transport with checked-IP dialing and ordinary TLS verification.

No provider SDK, inference adapter, environment proxies, redirects or automatic
retries. Only the public httpcore backend/stream interfaces are used.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import re
import ssl
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol
from uuid import UUID

import httpcore

from app.services.llm.credentials import (
    CredentialReceipt,
    ResolvedCredential,
    _pairs,
    validated_secret,
)
from app.services.llm.endpoint_policy import (
    EndpointRegistry,
    PinnedEndpoint,
    Purpose,
    Resolver,
    SystemResolver,
    resolve_destination,
)
from app.services.llm.errors import LlmSecurityError, SecurityCode
from app.services.llm.redaction import sensitive_io


class CredentialAuthorizer(Protocol):
    async def prepare(
        self, connection_id: UUID, pinned: PinnedEndpoint, purpose: Purpose
    ) -> ResolvedCredential: ...

    async def verify(self, receipt: CredentialReceipt, pinned: PinnedEndpoint) -> None: ...


@dataclass(frozen=True, slots=True)
class TransportLimits:
    connect_seconds: float = 5
    read_seconds: float = 60
    total_seconds: float = 90
    request_bytes: int = 1_048_576
    response_bytes: int = 1_048_576

    def __post_init__(self):
        for value in (self.connect_seconds, self.read_seconds, self.total_seconds):
            if type(value) not in (int, float) or not 0 < value <= 600:
                raise ValueError("invalid transport timeout")
        for value in (self.request_bytes, self.response_bytes):
            if type(value) is not int or not 1 <= value <= 8_388_608:
                raise ValueError("invalid transport byte limit")


class _PinnedStream(httpcore.AsyncNetworkStream):
    def __init__(self, stream, host, port, address, authorize, wire_limit):
        self._stream = stream
        self._host = host
        self._port = port
        self._address = address
        self._authorize = authorize
        self._wire_limit = wire_limit
        self._received = 0
        self._tls = False
        self.submitted = False

    def _peer_matches(self):
        peer = self._stream.get_extra_info("server_addr")
        if not isinstance(peer, tuple) or len(peer) < 2:
            return False
        address = None
        try:
            address = ipaddress.ip_address(peer[0])
        except (ValueError, TypeError):
            pass
        return address == ipaddress.ip_address(self._address) and peer[1] == self._port

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        if (
            not ssl_context.check_hostname
            or ssl_context.verify_mode != ssl.CERT_REQUIRED
            or server_hostname != self._host
            or self._tls
        ):
            raise LlmSecurityError(SecurityCode.TRANSPORT_UNSUPPORTED)
        self._stream = await self._stream.start_tls(
            ssl_context=ssl_context, server_hostname=server_hostname, timeout=timeout
        )
        if not self._peer_matches() or self._stream.get_extra_info("ssl_object") is None:
            await self.aclose()
            raise LlmSecurityError(SecurityCode.DESTINATION_DENIED)
        self._tls = True
        return self

    async def write(self, buffer, timeout=None):
        if not self._tls or not self._peer_matches():
            raise LlmSecurityError(SecurityCode.DESTINATION_DENIED)
        # Database transactions end before returning. Revoke/rotate during DNS/TLS
        # therefore blocks credentials from being written on this connection.
        await self._authorize()
        if buffer:
            self.submitted = True  # A write may partially succeed even if it later raises.
        await self._stream.write(buffer, timeout=timeout)

    async def read(self, max_bytes, timeout=None):
        data = await self._stream.read(min(max_bytes, 65536), timeout=timeout)
        self._received += len(data)
        if self._received > self._wire_limit:
            raise LlmSecurityError(SecurityCode.RESPONSE_REJECTED)
        return data

    async def aclose(self):
        await self._stream.aclose()

    def get_extra_info(self, info):
        return self._stream.get_extra_info(info)


class PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Dial only the selected validated numeric IP, retaining the origin for TLS/SNI."""

    def __init__(
        self,
        pinned: PinnedEndpoint,
        address: str,
        authorize: Callable[[], Awaitable[None]],
        wire_limit: int,
        backend: httpcore.AsyncNetworkBackend | None = None,
    ):
        self._pinned = pinned
        self._address = address
        self._authorize = authorize
        self._wire_limit = wire_limit
        self._backend = backend if backend is not None else httpcore.AnyIOBackend()
        self._stream = None

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if (
            host != self._pinned.approval.host
            or port != self._pinned.approval.port
            or local_address is not None
            or socket_options
        ):
            raise LlmSecurityError(SecurityCode.DESTINATION_DENIED)
        # AnyIO treats a numeric IP as an address; no second hostname resolution.
        stream = await self._backend.connect_tcp(host=self._address, port=port, timeout=timeout)
        pinned = _PinnedStream(stream, host, port, self._address, self._authorize, self._wire_limit)
        self._stream = pinned
        if not pinned._peer_matches():
            await pinned.aclose()
            raise LlmSecurityError(SecurityCode.DESTINATION_DENIED)
        return pinned

    async def connect_unix_socket(self, *args, **kwargs):
        raise LlmSecurityError(SecurityCode.DESTINATION_DENIED)

    async def aclose(self):
        # The pool does not own a stream until TLS setup completes. Close even
        # when setup fails or is cancelled before the pool receives the stream.
        if self._stream is not None:
            await self._stream.aclose()


def _extra_headers(pinned: PinnedEndpoint, values: tuple[tuple[str, str], ...]):
    if len(values) > 1:
        raise LlmSecurityError(SecurityCode.ENDPOINT_DENIED)
    headers = []
    for name, value in values:
        # Registered scheme option only. No generic tenant-defined header bag.
        if (
            pinned.approval.auth_scheme != "anthropic_api_key"
            or name.lower() != "anthropic-version"
            or value != "2023-06-01"
        ):
            raise LlmSecurityError(SecurityCode.ENDPOINT_DENIED)
        headers.append((b"anthropic-version", b"2023-06-01"))
    return headers


def _no_constant(value):
    raise ValueError("non-finite JSON constant")


def _safe_result(value, secret, depth=0):
    if depth > 64 or (isinstance(value, float) and not math.isfinite(value)):
        return False
    if isinstance(value, str):
        return secret not in value
    if isinstance(value, dict):
        return all(
            _safe_result(k, secret, depth + 1) and _safe_result(v, secret, depth + 1)
            for k, v in value.items()
        )
    if isinstance(value, list | tuple):
        return all(_safe_result(v, secret, depth + 1) for v in value)
    return True


@dataclass(frozen=True, slots=True)
class SecureResponse:
    status: int
    receipt: CredentialReceipt
    data: dict | list = field(repr=False)
    provider_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class TransportMetadata:
    receipt: CredentialReceipt | None = None
    submitted: bool = False
    http_status: int | None = None
    retry_after_seconds: float | None = None
    provider_request_id: str | None = None


class TransportFailure(LlmSecurityError):
    """Controlled metadata only; public() continues to expose just code/correlation."""

    def __init__(self, code, metadata):
        super().__init__(code)
        self.metadata = metadata


@dataclass
class _Progress:
    receipt: CredentialReceipt | None = None
    backend: PinnedNetworkBackend | None = None
    http_status: int | None = None
    retry_after_seconds: float | None = None
    provider_request_id: str | None = None

    def snapshot(self):
        stream = self.backend._stream if self.backend is not None else None
        return TransportMetadata(
            self.receipt,
            bool(stream and stream.submitted),
            self.http_status,
            self.retry_after_seconds,
            self.provider_request_id,
        )


def _safe_http_metadata(headers, secret):
    request_id = None
    retry_after = None
    for name, value in headers:
        if secret in value:
            continue
        if name.lower() in {b"x-request-id", b"request-id"}:
            if re.fullmatch(rb"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", value) and secret not in value:
                request_id = value.decode("ascii")
        elif name.lower() == b"retry-after" and len(value) <= 80:
            try:
                text = value.decode("ascii")
                if re.fullmatch(r"[0-9]{1,8}", text):
                    retry_after = float(min(int(text), 3600))
                else:
                    date = parsedate_to_datetime(text)
                    if date.tzinfo is not None:
                        retry_after = max(
                            0.0, min(3600.0, (date - datetime.now(UTC)).total_seconds())
                        )
            except (ValueError, UnicodeError, OverflowError, TypeError):
                pass
    return request_id, retry_after


class SecureJsonTransport:
    def __init__(
        self,
        endpoints: EndpointRegistry,
        credentials: CredentialAuthorizer,
        *,
        limits: TransportLimits | None = None,
        resolver: Resolver | None = None,
        network_backend: httpcore.AsyncNetworkBackend | None = None,
    ):
        self._endpoints = endpoints
        self._credentials = credentials
        self._limits = limits if limits is not None else TransportLimits()
        self._resolver = resolver if resolver is not None else SystemResolver()
        self._network_backend = network_backend  # Trusted test/backend injection, not request data.
        self._injected = network_backend is not None or resolver is not None

    @property
    def execution_origin(self):
        # Fake/injected DNS or wire behavior must never attest real worker qualification.
        return "live_network" if not self._injected else "synthetic_fixture"

    async def send(
        self,
        *,
        connection_id: UUID,
        pinned: PinnedEndpoint,
        url: str,
        purpose: Purpose,
        method: str = "POST",
        payload: dict | None = None,
        advanced_headers: tuple[tuple[str, str], ...] = (),
        timeout_seconds: float | None = None,
        expected_tenant_id: UUID | None = None,
    ) -> SecureResponse:
        failure = None
        progress = _Progress()
        timeout = self._limits.total_seconds
        if timeout_seconds is not None:
            if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 600:
                raise LlmSecurityError(SecurityCode.ENDPOINT_DENIED)
            timeout = min(timeout, timeout_seconds)
        with sensitive_io():
            try:
                async with asyncio.timeout(timeout):
                    return await self._send(
                        connection_id,
                        pinned,
                        url,
                        purpose,
                        method,
                        payload,
                        advanced_headers,
                        progress,
                        expected_tenant_id,
                    )
            except LlmSecurityError as error:
                failure = error.code
            except (TimeoutError, httpcore.TimeoutException):
                failure = SecurityCode.TIMEOUT
            except Exception:
                # Never propagate HTTP parser/TLS/driver exceptions or response bodies.
                failure = SecurityCode.TRANSPORT_FAILED
        raise TransportFailure(failure, progress.snapshot())

    async def _send(
        self,
        connection_id,
        pinned,
        url,
        purpose,
        method,
        payload,
        advanced_headers,
        progress,
        expected_tenant_id,
    ):
        normalized = self._endpoints.validate(pinned, url, purpose)
        if method not in {"POST", "GET"} or (method == "GET" and payload is not None):
            raise LlmSecurityError(SecurityCode.ENDPOINT_DENIED)
        extra = _extra_headers(pinned, advanced_headers)
        body = (
            None
            if payload is None
            else json.dumps(
                payload, allow_nan=False, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        )
        if (payload is not None and not isinstance(payload, dict)) or (
            body is not None and len(body) > self._limits.request_bytes
        ):
            raise LlmSecurityError(SecurityCode.RESPONSE_REJECTED)
        resolved = await self._credentials.prepare(connection_id, pinned, purpose)
        progress.receipt = resolved.receipt
        if (
            resolved.receipt.connection_id != connection_id
            or resolved.receipt.endpoint_approval_id != pinned.approval.approval_id
            or resolved.receipt.purpose != purpose
            or (expected_tenant_id is not None and resolved.receipt.tenant_id != expected_tenant_id)
        ):
            raise LlmSecurityError(SecurityCode.ACCESS_DENIED)
        secret = validated_secret(resolved.secret)
        if payload is not None and not _safe_result(payload, secret.decode("ascii")):
            raise LlmSecurityError(SecurityCode.CREDENTIAL_INVALID)
        address = await resolve_destination(pinned, self._resolver, self._limits.connect_seconds)
        headers = [
            (b"accept", b"application/json"),
            (b"content-type", b"application/json"),
            (b"accept-encoding", b"identity"),
            (b"connection", b"close"),
        ]
        if pinned.approval.auth_scheme == "bearer":
            headers.append((b"authorization", b"Bearer " + secret))
        else:
            headers.append((b"x-api-key", secret))
        headers.extend(extra)

        async def authorize():
            await self._credentials.verify(resolved.receipt, pinned)

        backend = PinnedNetworkBackend(
            pinned,
            address,
            authorize,
            self._limits.response_bytes * 2 + 65536,
            self._network_backend,
        )
        progress.backend = backend
        # No proxy handling or trust_env; httpcore never reads proxy environment variables.
        async with AsyncExitStack() as resources:
            resources.push_async_callback(backend.aclose)
            pool = await resources.enter_async_context(
                httpcore.AsyncConnectionPool(
                    ssl_context=ssl.create_default_context(),
                    network_backend=backend,
                    max_connections=1,
                    max_keepalive_connections=0,
                    http1=True,
                    http2=False,
                    retries=0,
                )
            )
            async with pool.stream(
                method,
                normalized,
                headers=headers,
                content=body,
                extensions={
                    "timeout": {
                        "connect": self._limits.connect_seconds,
                        "read": self._limits.read_seconds,
                        "write": self._limits.read_seconds,
                        "pool": self._limits.connect_seconds,
                    }
                },
            ) as response:
                progress.http_status = response.status
                if sum(len(k) + len(v) for k, v in response.headers) > 16384:
                    raise LlmSecurityError(SecurityCode.RESPONSE_REJECTED)
                progress.provider_request_id, progress.retry_after_seconds = _safe_http_metadata(
                    response.headers, secret
                )
                if 300 <= response.status < 400:
                    raise LlmSecurityError(SecurityCode.ENDPOINT_DENIED)
                if response.status < 200 or response.status >= 300:
                    # No upstream error-body parsing, storage, logging, or echo.
                    raise LlmSecurityError(SecurityCode.UPSTREAM_FAILED)
                header_map = {name.lower(): value for name, value in response.headers}
                if header_map.get(b"content-encoding", b"identity").lower() != b"identity":
                    raise LlmSecurityError(SecurityCode.RESPONSE_REJECTED)
                media = header_map.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
                if media != b"application/json":
                    raise LlmSecurityError(SecurityCode.RESPONSE_REJECTED)
                length = header_map.get(b"content-length")
                if length is not None and (
                    not length.isdigit() or int(length) > self._limits.response_bytes
                ):
                    raise LlmSecurityError(SecurityCode.RESPONSE_REJECTED)
                chunks = []
                size = 0
                async for chunk in response.aiter_stream():
                    size += len(chunk)
                    if size > self._limits.response_bytes:
                        raise LlmSecurityError(SecurityCode.RESPONSE_REJECTED)
                    chunks.append(chunk)
                data = json.loads(
                    b"".join(chunks).decode("utf-8"),
                    object_pairs_hook=_pairs,
                    parse_constant=_no_constant,
                )
                if not isinstance(data, dict | list):
                    raise LlmSecurityError(SecurityCode.RESPONSE_REJECTED)
                # An upstream service must not be able to reflect our credential into results.
                if not _safe_result(data, secret.decode("ascii")):
                    raise LlmSecurityError(SecurityCode.RESPONSE_REJECTED)
                return SecureResponse(
                    response.status, resolved.receipt, data, progress.provider_request_id
                )
