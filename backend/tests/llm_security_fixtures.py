"""Only ephemeral keys, synthetic rows/DNS, and an in-memory fake wire backend."""

import base64
import json
import os
from types import SimpleNamespace

import httpcore
import pytest_asyncio
from agent_schema_fixtures import seed_agents, seed_legacy, uid
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.llm import LlmConnection
from app.services.agents.persistence_types import EndpointPolicyRecord
from app.services.llm.credentials import (
    CredentialReceipt,
    KeyRing,
    ResolvedCredential,
)
from app.services.llm.endpoint_policy import ApprovedEndpoint, EndpointRegistry, OperatorPolicy
from app.services.llm.errors import LlmSecurityError, SecurityCode

SENTINEL = "synthetic-credential-never-a-real-key-8uJn9W"


def keys(active="v1", *, old=True):
    data = {"v2": base64.urlsafe_b64encode(os.urandom(32)).decode()}
    if old:
        data["v1"] = base64.urlsafe_b64encode(os.urandom(32)).decode()
    return KeyRing.parse(SecretStr(json.dumps(data)), active)


def endpoint(scheme="bearer", host="gateway.example.invalid"):
    approval = ApprovedEndpoint(
        approval_id=uid(70), host=host, path_prefix="/v1", auth_scheme=scheme
    )
    registry = EndpointRegistry(OperatorPolicy(endpoints=(approval,)))
    return registry, registry.pin(
        EndpointPolicyRecord(host=host, path_prefix="/v1", approval_id=uid(70))
    )


@pytest_asyncio.fixture
async def sessions():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as session:
        await seed_legacy(session)
        await seed_agents(session)
        row = await session.get(LlmConnection, uid(5))
        row.endpoint_policy = {
            "host": "gateway.example.invalid",
            "path_prefix": "/v1",
            "approval_id": str(uid(70)),
        }
        row.enabled = True  # Synthetic database only, never a real profile/provider.
    yield factory
    await engine.dispose()


class FakeResolver:
    def __init__(self, *answers):
        self.answers = answers or (("8.8.8.8",),)
        self.calls = []

    async def resolve(self, host, port):
        self.calls.append((host, port))
        return self.answers[min(len(self.calls) - 1, len(self.answers) - 1)]


class FakeAuthorizer:
    def __init__(self):
        self.prepares = 0
        self.verifies = 0
        self.enabled = True
        self.version = 1

    async def prepare(self, connection_id, pinned, purpose):
        self.prepares += 1
        if not self.enabled:
            raise LlmSecurityError(SecurityCode.CONNECTION_DISABLED)
        return ResolvedCredential(
            CredentialReceipt(
                attempt_id=uid(80 + self.prepares),
                tenant_id=uid(1),
                actor_id=uid(9),
                connection_id=connection_id,
                credential_id=uid(50 + self.version),
                credential_version=self.version,
                key_version="v1",
                endpoint_approval_id=uid(70),
                purpose=purpose,
            ),
            SecretStr(SENTINEL),
        )

    async def verify(self, receipt, pinned):
        self.verifies += 1
        if not self.enabled:
            raise LlmSecurityError(SecurityCode.CONNECTION_DISABLED)
        if self.version != receipt.credential_version:
            raise LlmSecurityError(SecurityCode.CREDENTIAL_CHANGED)


class FakeStream(httpcore.AsyncNetworkStream):
    def __init__(self, response, peer=("8.8.8.8", 443), *, tls=True, on_tls=None):
        self.response = response
        self.peer = peer
        self.has_tls = tls
        self.on_tls = on_tls
        self.tls_options = None
        self.writes = []
        self.closed = False

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.tls_options = (ssl_context, server_hostname)
        if self.on_tls:
            await self.on_tls()
        return self

    async def write(self, buffer, timeout=None):
        self.writes.append(buffer)

    async def read(self, max_bytes, timeout=None):
        part, self.response = self.response[:max_bytes], self.response[max_bytes:]
        return part

    async def aclose(self):
        self.closed = True

    def get_extra_info(self, name):
        if name == "server_addr":
            return self.peer
        if name == "ssl_object":
            return (
                SimpleNamespace(selected_alpn_protocol=lambda: "http/1.1") if self.has_tls else None
            )
        return None


class FakeBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, response=None, **stream_options):
        self.calls = []
        self.stream = FakeStream(response or wire_response(), **stream_options)

    async def connect_tcp(self, host, port, timeout=None, **kwargs):
        self.calls.append((host, port))
        return self.stream


def wire_response(body=b'{"ok":true}', *, status=b"200 OK", headers=()):
    return (
        b"HTTP/1.1 "
        + status
        + b"\r\nContent-Type: application/json\r\nContent-Length: "
        + str(len(body)).encode()
        + b"\r\n"
        + b"".join(name + b": " + value + b"\r\n" for name, value in headers)
        + b"\r\n"
        + body
    )
