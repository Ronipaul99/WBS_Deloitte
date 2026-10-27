"""Operator-owned exact egress approvals and conservative URL/DNS validation."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator

from app.services.agents.persistence_types import EndpointPolicyRecord
from app.services.llm.contracts import Contract, Identity, unique
from app.services.llm.credentials import _pairs
from app.services.llm.errors import LlmSecurityError, SecurityCode

AuthScheme = Literal["bearer", "anthropic_api_key", "gateway_api_key"]
Purpose = Literal["discovery", "test", "inference"]


def _deny():
    return LlmSecurityError(SecurityCode.ENDPOINT_DENIED)


def canonical_host(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 253
        or any(ord(char) <= 32 for char in value)
        or any(char in value for char in "%/@\\[]")
        or value.endswith(".")
        or value.startswith(".")
    ):
        raise _deny()
    result = None
    try:
        result = ipaddress.ip_address(value).compressed
    except ValueError:
        pass
    if result is not None:
        public_ip(result)
        return result
    result = None
    try:
        result = value.encode("idna").decode("ascii").lower()
    except UnicodeError:
        pass
    if (
        result is None
        or len(result) > 253
        or "." not in result
        or not all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
            for part in result.split(".")
        )
        or all(re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]+)", part) for part in result.split("."))
    ):
        raise _deny()
    return result


def canonical_path(value: str) -> str:
    # Reject ambiguous encoding instead of repeatedly decoding differently from gateways.
    if (
        not isinstance(value, str)
        or len(value) > 2048
        or not re.fullmatch(r"/[A-Za-z0-9._~/-]*", value)
        or "//" in value
        or any(segment in {".", ".."} for segment in value.split("/"))
    ):
        raise _deny()
    return value


def public_ip(value: str):
    if not isinstance(value, str):
        raise LlmSecurityError(SecurityCode.DNS_DENIED)
    address = None
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        pass
    if address is None or "%" in value:
        raise LlmSecurityError(SecurityCode.DNS_DENIED)
    prohibited = (
        "168.63.129.16/32",
        "192.0.0.0/24",
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "2002::/16",
        "2001::/32",
    )
    if (
        not address.is_global
        or address.is_multicast
        or address.is_reserved
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or (isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None)
        or any(address in ipaddress.ip_network(network) for network in prohibited)
    ):
        raise LlmSecurityError(SecurityCode.DNS_DENIED)
    return address


class ApprovedEndpoint(Contract):
    approval_id: Identity
    host: Annotated[str, Field(strict=True, min_length=1, max_length=253)]
    port: Annotated[int, Field(strict=True, ge=1, le=65535)] = 443
    path_prefix: Annotated[str, Field(strict=True, min_length=1, max_length=500)]
    auth_scheme: AuthScheme
    purposes: Annotated[tuple[Purpose, ...], Field(min_length=1, max_length=3)] = (
        "discovery",
        "test",
        "inference",
    )

    @model_validator(mode="after")
    def normalized(self):
        object.__setattr__(self, "host", canonical_host(self.host))
        prefix = canonical_path(self.path_prefix).rstrip("/") or "/"
        object.__setattr__(self, "path_prefix", prefix)
        unique(self.purposes)
        return self


class OperatorPolicy(Contract):
    endpoints: Annotated[tuple[ApprovedEndpoint, ...], Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def distinct_ids(self):
        unique(tuple(item.approval_id for item in self.endpoints))
        return self


@dataclass(frozen=True, slots=True)
class PinnedEndpoint:
    """Server-created snapshot, not proof of operator approval by itself."""

    approval: ApprovedEndpoint

    @property
    def base_url(self):
        item = self.approval
        host = f"[{item.host}]" if ":" in item.host else item.host
        port = "" if item.port == 443 else f":{item.port}"
        return f"https://{host}{port}"


class EndpointRegistry:
    def __init__(self, policy: OperatorPolicy):
        self._policy = policy

    def approved_endpoints(self):
        """Non-secret operator choices; callers must enforce administrator permission."""
        return self._policy.endpoints

    @classmethod
    def parse(cls, source: SecretStr | None):
        import json

        policy = None
        try:
            raw = source.get_secret_value() if source is not None else ""
            if len(raw.encode("utf-8")) > 65536:
                raise ValueError("oversized operator policy")
            policy = OperatorPolicy.model_validate(json.loads(raw, object_pairs_hook=_pairs))
        except (ValueError, TypeError, LlmSecurityError):
            pass
        if policy is None:
            raise _deny()
        return cls(policy)

    def pin(self, record: EndpointPolicyRecord) -> PinnedEndpoint:
        for item in self._policy.endpoints:
            if (
                record.approval_id == item.approval_id
                and record.scheme == "https"
                and canonical_host(record.host) == item.host
                and record.port == item.port
                and (canonical_path(record.path_prefix).rstrip("/") or "/") == item.path_prefix
            ):
                return PinnedEndpoint(item)
        raise _deny()

    def validate(self, pinned: PinnedEndpoint, url: str, purpose: Purpose) -> str:
        item = pinned.approval
        if item not in self._policy.endpoints or purpose not in item.purposes:
            raise _deny()
        if (
            not isinstance(url, str)
            or len(url) > 4096
            or any(ord(char) < 33 or ord(char) == 127 for char in url)
            or any(char in url for char in "\\%?#")
        ):
            raise _deny()
        parsed = None
        try:
            candidate = urlsplit(url)
            port = candidate.port if candidate.port is not None else 443
            if (
                candidate.scheme != "https"
                or candidate.username is not None
                or candidate.password is not None
                or candidate.hostname is None
                or candidate.netloc.endswith(":")
            ):
                raise ValueError("invalid URL")
            host = canonical_host(candidate.hostname)
            path = canonical_path(candidate.path or "/")
            parsed = (host, port, path)
        except (ValueError, LlmSecurityError):
            pass
        if parsed is None:
            raise _deny()
        host, port, path = parsed
        if (
            host != item.host
            or port != item.port
            or not (
                item.path_prefix == "/"
                or path == item.path_prefix
                or path.startswith(item.path_prefix + "/")
            )
        ):
            raise _deny()
        return pinned.base_url + path


class Resolver(Protocol):
    async def resolve(self, host: str, port: int) -> tuple[str, ...]: ...


class SystemResolver:
    async def resolve(self, host: str, port: int) -> tuple[str, ...]:
        results = await asyncio.get_running_loop().getaddrinfo(
            host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
        return tuple(dict.fromkeys(item[4][0] for item in results))


async def resolve_destination(pinned: PinnedEndpoint, resolver: Resolver, timeout: float):
    addresses = None
    try:
        async with asyncio.timeout(timeout):
            addresses = await resolver.resolve(pinned.approval.host, pinned.approval.port)
    except (OSError, TimeoutError):
        pass
    if not addresses or len(addresses) > 32:
        raise LlmSecurityError(SecurityCode.DNS_DENIED)
    validated = tuple(public_ip(value).compressed for value in addresses)
    return validated[0]  # All answers were checked; connect to this literal, never the hostname.
