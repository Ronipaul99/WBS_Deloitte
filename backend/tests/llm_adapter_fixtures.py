"""Sanitized protocol fixtures and fake multi-attempt wire. Never creates real sockets."""

import json
from pathlib import Path

import httpcore
from llm_security_fixtures import FakeAuthorizer, FakeResolver, FakeStream, endpoint, wire_response

from app.services.agents.contracts import OUTPUT_CONTRACTS
from app.services.llm.adapter_types import (
    AdapterOptions,
    AttemptPolicy,
    CallBudget,
    QualificationBinding,
    fingerprint,
)
from app.services.llm.contracts import GenerationRequest
from app.services.llm.registry import create_provider
from app.services.llm.secure_transport import SecureJsonTransport

ROOT = Path(__file__).parent
PROVIDERS = ("openai", "anthropic", "openai_compatible")


def request(provider="openai", *, schema="facts.v1", native=False, **overrides):
    data = json.loads((ROOT / "agent_contract_fixtures/provider-requests.json").read_text())[
        provider
    ]
    data["profile"]["capabilities"].update(
        context_tokens=65536, output_tokens=4096, native_tools="supported" if native else "unknown"
    )
    data.update(response_schema=schema, input_token_budget=20_000, max_output_tokens=256)
    data.update(overrides)
    return GenerationRequest.model_validate(data)


def content(schema="facts.v1"):
    if schema == "facts.v1":
        data = {"facts": [], "requirements": [], "unresolved_categories": []}
    elif schema == "analyst.v1":
        data = {"no_facts_reason": "irrelevant_material"}
    elif schema == "writer_fragment.v1":
        data = {"claims": [], "key_points": [], "omitted": []}
    elif schema == "verification.v1":
        data = {"checked_claim_ids": []}
    else:
        source = json.loads(
            (ROOT / "agent_contract_fixtures/summary.json").read_text(encoding="utf-8")
        )
        data = {key: source[key] for key in ("executive_overview", "sections", "key_points")}
    return OUTPUT_CONTRACTS[schema].model_validate(data).model_dump(mode="json")


def reply(
    provider,
    value=None,
    *,
    status="completed",
    counts="default",
    model="synthetic-model-not-a-live-model",
    tool="lookup_definition",
    arguments=None,
    call_id="call_synthetic",
):
    text = (
        value if isinstance(value, str) else json.dumps(value if value is not None else content())
    )
    arguments = arguments if arguments is not None else {"term": "synthetic-term"}
    if provider == "openai":
        output = [{"type": "message", "content": [{"type": "output_text", "text": text}]}]
        result = {"id": "resp_synthetic", "status": "completed", "model": model, "output": output}
        if status == "tool_actions":
            result["output"] = [
                {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": tool,
                    "arguments": json.dumps(arguments),
                }
            ]
        elif status == "refused":
            result["output"] = [
                {
                    "type": "message",
                    "content": [{"type": "refusal", "refusal": "Synthetic refusal"}],
                }
            ]
        elif status == "truncated":
            result.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
        usage = {"input_tokens": 10, "output_tokens": 5}
    elif provider == "anthropic":
        result = {
            "id": "msg_synthetic",
            "model": model,
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": text}],
        }
        if status == "tool_actions":
            result.update(
                stop_reason="tool_use",
                content=[{"type": "tool_use", "id": call_id, "name": tool, "input": arguments}],
            )
        elif status == "refused":
            result["stop_reason"] = "refusal"
        elif status == "truncated":
            result["stop_reason"] = "max_tokens"
        usage = {"input_tokens": 10, "output_tokens": 5}
    else:
        message = {"role": "assistant", "content": text}
        result = {
            "id": "chat_synthetic",
            "model": model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
        }
        if status == "tool_actions":
            message.update(
                content=None,
                tool_calls=[
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": tool, "arguments": json.dumps(arguments)},
                    }
                ],
            )
            result["choices"][0]["finish_reason"] = "tool_calls"
        elif status == "refused":
            result["choices"][0]["finish_reason"] = "content_filter"
        elif status == "truncated":
            result["choices"][0]["finish_reason"] = "length"
        usage = {"prompt_tokens": 10, "completion_tokens": 5}
    if counts is not None:
        result["usage"] = usage if counts == "default" else counts
    return result


def wire(data, *, status=b"200 OK", headers=()):
    return wire_response(
        json.dumps(data).encode(),
        status=status,
        headers=((b"x-request-id", b"req_synthetic"), *headers),
    )


class SequenceBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, *attempts, on_connect=None):
        self.attempts = attempts
        self.calls, self.streams = [], []
        self.on_connect = on_connect

    async def connect_tcp(self, host, port, timeout=None, **kwargs):
        self.calls.append((host, port))
        if self.on_connect:
            await self.on_connect(len(self.calls))
        value = self.attempts[min(len(self.calls) - 1, len(self.attempts) - 1)]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, FakeStream):
            stream = value
        else:
            stream = FakeStream(value)
        self.streams.append(stream)
        return stream

    def payload(self, index=0):
        sent = b"".join(self.streams[index].writes)
        return json.loads(sent.split(b"\r\n\r\n", 1)[1])


class FakeClock:
    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def __call__(self):
        return self.now

    async def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay


def adapter(
    req=None,
    *responses,
    budget=None,
    policy=None,
    auth=None,
    resolver=None,
    backend=None,
    options=None,
    clock=None,
):
    req = req or request()
    options = options or AdapterOptions()
    scheme = "anthropic_api_key" if req.profile.provider == "anthropic" else "bearer"
    registry, pinned = endpoint(scheme)
    backend = backend or SequenceBackend(*(responses or (wire(reply(req.profile.provider)),)))
    auth = auth or FakeAuthorizer()
    transport = SecureJsonTransport(
        registry, auth, resolver=resolver or FakeResolver(), network_backend=backend
    )
    budget = budget or CallBudget(max_calls=8, max_tokens=100_000, total_seconds=120, clock=clock)
    qualification = QualificationBinding(
        qualification_id=req.profile.capabilities.qualification_id,
        tested_at=req.profile.capabilities.tested_at,
        origin="synthetic_fixture",
        fingerprint=fingerprint(req.profile, pinned, options),
    )
    provider = create_provider(
        transport,
        req.profile,
        pinned,
        budget,
        qualification=qualification,
        options=options,
        policy=policy or AttemptPolicy(),
        sleep=clock.sleep if clock else None,
    )
    return provider, backend, auth
