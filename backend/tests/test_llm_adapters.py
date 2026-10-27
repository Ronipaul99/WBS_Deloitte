"""Step 4 adapters over the Step 3 fake wire; --noconftest avoids shared cleanup."""

import asyncio
import json
import logging

import httpcore
import pytest
from agent_schema_fixtures import uid
from llm_adapter_fixtures import (
    PROVIDERS,
    FakeClock,
    SequenceBackend,
    adapter,
    content,
    reply,
    request,
    wire,
)
from llm_security_fixtures import SENTINEL, FakeAuthorizer, FakeResolver, FakeStream
from pydantic import ValidationError

from app.services.agents.contracts import OUTPUT_CONTRACTS
from app.services.llm.adapter_types import AdapterOptions, AttemptPolicy, CallBudget
from app.services.llm.contracts import GenerationRequest, GenerationResult, ToolExchange
from app.services.llm.protocol_support import InvalidOutput, project_schema, wire_input
from app.services.llm.secure_transport import SecureJsonTransport


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("schema", tuple(OUTPUT_CONTRACTS))
async def test_same_task_is_locally_validated_across_adapters(provider, schema):
    req = request(provider, schema=schema)
    client, backend, auth = adapter(req, wire(reply(provider, content(schema))))
    result = await client.generate(req)
    assert result.status == "completed" and result.request_id == req.request_id
    assert OUTPUT_CONTRACTS[schema].model_validate_json(result.output_json).model_dump(
        mode="json"
    ) == content(schema)
    assert result.provider_request_id == "req_synthetic"
    assert result.usage.input_tokens == 10 and result.usage.output_tokens == 5
    assert auth.prepares == 1 and client.budget.records[0].receipt.credential_version == 1
    assert backend.calls == [("8.8.8.8", 443)]
    assert SENTINEL not in json.dumps(backend.payload()) + result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("native_schema", [False, True])
async def test_protocol_specific_limits_system_schema_and_sampling(provider, native_schema):
    req = request(
        provider,
        output_mode="native_json_schema" if native_schema else "validated_json",
        temperature=0.5,
        messages=[
            {"role": "system", "content": "Synthetic role instructions"},
            {"role": "user", "content": "Synthetic evidence"},
        ],
    )
    client, backend, _ = adapter(req)
    assert (await client.generate(req)).status == "completed"
    payload = backend.payload()
    assert payload["model"] == req.profile.model_id and payload["temperature"] == 0.5
    assert payload["stream"] is False
    if provider == "openai":
        assert payload["max_output_tokens"] == 256 and payload["store"] is False
        assert "Synthetic role instructions" in payload["instructions"]
        assert ("text" in payload) == native_schema
    elif provider == "anthropic":
        assert payload["max_tokens"] == 256 and "Synthetic role instructions" in payload["system"]
        assert ("output_config" in payload) == native_schema
        assert b"anthropic-version: 2023-06-01" in b"".join(backend.streams[0].writes)
    else:
        assert payload["max_tokens"] == 256 and payload["messages"][0]["role"] == "system"
        assert ("response_format" in payload) == native_schema


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_native_tool_calls_and_tool_result_ids_map_without_execution(provider):
    req = request(provider, native=True, allowed_tools=["lookup_definition"])
    client, backend, _ = adapter(req, wire(reply(provider, status="tool_actions")))
    result = await client.generate(req)
    assert result.status == "tool_actions" and len(result.actions) == 1
    assert result.actions[0].call_id == "call_synthetic"
    assert result.actions[0].arguments.name == "lookup_definition"
    exchange = ToolExchange(
        action=result.actions[0], output_json='{"definition":"synthetic"}', is_error=True
    )
    following = GenerationRequest.model_validate({**req.model_dump(), "tool_results": [exchange]})
    client, backend, _ = adapter(following)
    assert (await client.generate(following)).status == "completed"
    payload = backend.payload()
    assert "call_synthetic" in json.dumps(payload) and "synthetic" in json.dumps(payload)
    if provider == "openai":
        assert payload["input"][-1]["type"] == "function_call_output"
        assert payload["input"][-1]["call_id"] == result.actions[0].call_id
    elif provider == "anthropic":
        assert payload["messages"][-1]["content"][0]["tool_use_id"] == result.actions[0].call_id
        assert payload["messages"][-1]["content"][0]["is_error"] is True
    else:
        assert payload["messages"][-1]["role"] == "tool"
        assert payload["messages"][-1]["tool_call_id"] == result.actions[0].call_id


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_tested_json_action_envelope_path_for_non_native_models(provider):
    req = request(provider, allowed_tools=["lookup_definition"])
    value = {
        "kind": "tool_actions",
        "actions": [
            {
                "call_id": "json_call",
                "arguments": {"name": "lookup_definition", "term": "synthetic-term"},
            }
        ],
    }
    client, backend, _ = adapter(req, wire(reply(provider, value)))
    result = await client.generate(req)
    assert result.status == "tool_actions" and result.actions[0].call_id == "json_call"
    assert "tools" not in backend.payload()
    final = {"kind": "completed", "content": content()}
    client, _, _ = adapter(req, wire(reply(provider, final)))
    assert (await client.generate(req)).status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("status", ["refused", "truncated"])
async def test_refusal_and_truncation_are_terminal_without_repair(provider, status):
    req = request(provider)
    client, backend, _ = adapter(req, wire(reply(provider, status=status)))
    result = await client.generate(req)
    assert result.status == status and result.output_json is None and len(backend.calls) == 1
    assert not client.budget.records[0].repair


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize(
    "bad",
    [
        "not-json",
        '{"facts":[],"facts":[]}',
        '{"tenant_id":"bad"}',
        '{"unresolved_categories":["invalid"]}',
        '{"facts":NaN}',
    ],
)
async def test_one_format_repair_is_shared_bounded_and_does_not_echo_invalid_output(provider, bad):
    req = request(provider)
    client, backend, auth = adapter(req, wire(reply(provider, bad)), wire(reply(provider)))
    result = await client.generate(req)
    assert result.status == "completed" and auth.prepares == 2
    assert [r.repair for r in client.budget.records] == [False, True]
    assert result.usage.input_tokens == 20
    assert "previous response did not match" in json.dumps(backend.payload(1))
    assert bad not in json.dumps(backend.payload(1))


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize(
    "tool,args",
    [
        ("shell", {}),
        ("lookup_definition", {"term": "x", "tenant_id": "bad"}),
        ("lookup_definition", {"term": ""}),
    ],
)
async def test_unknown_tools_and_invalid_arguments_never_escape_validation(provider, tool, args):
    req = request(provider, native=True, allowed_tools=["lookup_definition"])
    client, backend, _ = adapter(
        req, wire(reply(provider, status="tool_actions", tool=tool, arguments=args))
    )
    result = await client.generate(req)
    assert result.status == "failed" and result.failure.code == "invalid_schema"
    assert not result.actions and len(backend.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("http_status", [401, 403, 400, 404, 422])
async def test_auth_and_configuration_http_failures_do_not_retry_or_echo_bodies(
    provider, http_status
):
    req = request(provider)
    client, backend, _ = adapter(
        req, wire({"error": SENTINEL}, status=f"{http_status} Error".encode())
    )
    result = await client.generate(req)
    assert result.status == "failed" and result.failure.code == "configuration"
    assert len(backend.calls) == 1 and SENTINEL not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_retry_after_and_format_repair_share_total_attempt_and_usage_budget(provider):
    req = request(provider)
    clock = FakeClock()
    client, backend, auth = adapter(
        req,
        wire({}, status=b"429 Too Many Requests", headers=((b"Retry-After", b"2"),)),
        wire(reply(provider, "invalid-json")),
        wire(reply(provider)),
        clock=clock,
    )
    result = await client.generate(req)
    assert result.status == "completed" and result.usage.source == "unknown"
    assert auth.prepares == 3 and clock.sleeps == [2.0]
    assert [r.repair for r in client.budget.records] == [False, False, True]
    assert client.budget.calls == 3 and len(backend.calls) == 3
    assert client.budget.records[0].http_status == 429


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_permanently_bad_format_has_only_one_repair_even_across_repeated_calls(provider):
    req = request(provider)
    client, backend, _ = adapter(req, wire(reply(provider, "bad-json")))
    result = await client.generate(req)
    assert result.failure.code == "invalid_schema" and len(backend.calls) == 2
    again = await client.generate(req)
    assert again.failure.code == "budget_exhausted" and len(backend.calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("calls,tokens", [(1, 100000), (8, 20256)])
async def test_global_budget_exhaustion_stops_a_format_repair_before_send(calls, tokens):
    req = request()
    budget = CallBudget(max_calls=calls, max_tokens=tokens, total_seconds=10)
    client, backend, _ = adapter(req, wire(reply("openai", "invalid")), budget=budget)
    result = await client.generate(req)
    assert result.failure.code == "budget_exhausted" and len(backend.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("delay", [b"9999", b"6"])
async def test_retry_after_beyond_policy_is_not_retried_early(delay):
    clock = FakeClock()
    client, backend, _ = adapter(
        request(),
        wire({}, status=b"429 Rate Limited", headers=((b"Retry-After", delay),)),
        clock=clock,
    )
    assert (await client.generate(request())).status == "failed"
    assert len(backend.calls) == 1 and not clock.sleeps


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_timeout_after_submit_is_unknown_usage_and_not_automatically_retried(provider):
    stream = FakeStream(b"")

    async def timeout(*args, **kwargs):
        raise httpcore.ReadTimeout(SENTINEL)

    stream.read = timeout
    req = request(provider)
    client, backend, _ = adapter(req, backend=SequenceBackend(stream))
    result = await client.generate(req)
    assert result.status == "failed" and result.usage.source == "unknown"
    assert client.budget.records[0].submitted and len(backend.calls) == 1
    assert SENTINEL not in result.model_dump_json()


@pytest.mark.asyncio
async def test_explicit_ambiguous_retry_policy_keeps_unknown_billing_and_fresh_credential():
    stream = FakeStream(b"")

    async def timeout(*args, **kwargs):
        raise httpcore.ReadTimeout("synthetic timeout")

    stream.read = timeout
    client, backend, auth = adapter(
        request(),
        backend=SequenceBackend(stream, wire(reply("openai"))),
        policy=AttemptPolicy(retry_ambiguous_submission=True),
        clock=FakeClock(),
    )
    result = await client.generate(request())
    assert result.status == "completed" and result.usage.source == "unknown"
    assert auth.prepares == 2 and len(backend.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_retry_resolves_rotation_and_blocks_revocation(provider):
    req = request(provider)
    auth, clock = FakeAuthorizer(), FakeClock()

    async def rotate(delay):
        auth.version += 1

    client, _, _ = adapter(
        req, wire({}, status=b"429 Rate Limited"), wire(reply(provider)), auth=auth, clock=clock
    )
    client._sleep = rotate
    assert (await client.generate(req)).status == "completed"
    assert [r.receipt.credential_version for r in client.budget.records] == [1, 2]
    auth = FakeAuthorizer()

    async def disable(delay):
        auth.enabled = False

    client, backend, _ = adapter(
        req, wire({}, status=b"429 Rate Limited"), wire(reply(provider)), auth=auth
    )
    client._sleep = disable
    result = await client.generate(req)
    assert result.failure.code == "configuration" and len(backend.calls) == 1


@pytest.mark.asyncio
async def test_rotation_during_tls_before_a_repair_write_blocks_stale_credential():
    req = request()
    auth = FakeAuthorizer()

    async def rotate():
        auth.version += 1

    second = FakeStream(wire(reply("openai")), on_tls=rotate)
    client, backend, _ = adapter(
        req, backend=SequenceBackend(wire(reply("openai", "bad-json")), second), auth=auth
    )
    result = await client.generate(req)
    assert result.failure.code == "configuration" and not second.writes
    assert len(backend.calls) == 2 and auth.prepares == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize(
    "counts", [None, {"input_tokens": 10}, {"input_tokens": True, "output_tokens": 1}]
)
async def test_absent_or_partial_usage_is_not_invented_as_zero(provider, counts):
    req = request(provider)
    client, _, _ = adapter(req, wire(reply(provider, counts=counts)))
    result = await client.generate(req)
    assert result.status == "completed" and result.usage.source == "unknown"
    assert result.usage.input_tokens is None and result.usage.output_tokens is None


@pytest.mark.asyncio
async def test_anthropic_cache_tokens_are_included_in_reported_input_usage():
    req = request("anthropic")
    counts = {
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_creation_input_tokens": 7,
        "cache_read_input_tokens": 8,
    }
    client, _, _ = adapter(req, wire(reply("anthropic", counts=counts)))
    assert (await client.generate(req)).usage.input_tokens == 25


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", [{"model_id": "other-model"}, {"profile_version": 2}, {"tenant_id": uid(101)}]
)
async def test_pinned_profile_mismatch_is_denied_before_any_network(change):
    req = request()
    client, backend, auth = adapter(req)
    modified = GenerationRequest.model_validate(
        {**req.model_dump(), "profile": {**req.profile.model_dump(), **change}}
    )
    result = await client.generate(modified)
    assert result.failure.code == "configuration" and not backend.calls and auth.prepares == 0


@pytest.mark.asyncio
async def test_qualification_cannot_be_reused_after_an_endpoint_or_option_change():
    req = request("openai_compatible")
    client, backend, _ = adapter(req)
    client.options = AdapterOptions(compatible_token_parameter="max_completion_tokens")
    assert (await client.generate(req)).failure.code == "configuration"
    assert not backend.calls


@pytest.mark.asyncio
async def test_live_transport_rejects_synthetic_qualification_before_network():
    req = request()
    client, _, _ = adapter(req)
    client.transport = SecureJsonTransport(client.transport._endpoints, FakeAuthorizer())
    assert (await client.generate(req)).failure.code == "configuration"


@pytest.mark.asyncio
async def test_unqualified_or_wrong_auth_scheme_never_makes_a_request():
    req = request()
    client, backend, _ = adapter(req)
    client.qualification = None
    assert (await client.generate(req)).failure.code == "configuration"
    assert not backend.calls


@pytest.mark.asyncio
async def test_unsupported_provider_settings_and_injected_options_fail_closed():
    req = request("anthropic", temperature=1.5)
    client, backend, _ = adapter(req)
    assert (await client.generate(req)).failure.code == "configuration" and not backend.calls
    with pytest.raises(ValidationError):
        AdapterOptions(arbitrary_header="value")
    with pytest.raises(ValidationError):
        request(temperature=float("nan"))


@pytest.mark.asyncio
async def test_compatible_token_limit_dialect_is_explicit_and_bound_to_qualification():
    req = request("openai_compatible")
    client, backend, _ = adapter(
        req, options=AdapterOptions(compatible_token_parameter="max_completion_tokens")
    )
    assert (await client.generate(req)).status == "completed"
    assert (
        backend.payload()["max_completion_tokens"] == 256 and "max_tokens" not in backend.payload()
    )


@pytest.mark.asyncio
async def test_input_admission_includes_schema_and_tool_history_without_silent_truncation():
    req = request(input_token_budget=1)
    client, backend, _ = adapter(req)
    assert (await client.generate(req)).failure.code == "context_overflow"
    assert not backend.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_mismatched_returned_model_and_oversized_body_are_not_success(provider):
    req = request(provider)
    client, _, _ = adapter(req, wire(reply(provider, model="different-model")))
    assert (await client.generate(req)).failure.code == "invalid_schema"
    huge = wire({"padding": "x" * 1_050_000})
    client, backend, _ = adapter(req, huge)
    assert (await client.generate(req)).status == "failed" and len(backend.calls) == 1


@pytest.mark.asyncio
async def test_transport_security_is_applied_to_every_adapter_operation(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    client, backend, _ = adapter(
        request(),
        wire({}, status=b"302 Found", headers=((b"Location", b"http://169.254.169.254/"),)),
    )
    assert (await client.generate(request())).failure.code == "configuration"
    assert len(backend.calls) == 1
    client, backend, _ = adapter(request(), resolver=FakeResolver(("8.8.8.8", "127.0.0.1")))
    assert (await client.generate(request())).failure.code == "configuration" and not backend.calls


@pytest.mark.asyncio
async def test_response_log_reflection_and_all_metadata_remain_secret_free(caplog):
    req = request()
    client, _, _ = adapter(req, wire(reply("openai"), headers=((b"X-Echo", SENTINEL.encode()),)))
    with caplog.at_level(logging.DEBUG):
        result = await client.generate(req)
    assert SENTINEL not in (
        result.model_dump_json()
        + caplog.text
        + json.dumps([r.model_dump(mode="json") for r in client.budget.records])
    )


@pytest.mark.asyncio
async def test_cancelled_request_propagates_and_has_unknown_usage_no_retry():
    stream = FakeStream(b"")

    async def cancel(*args, **kwargs):
        raise asyncio.CancelledError()

    stream.read = cancel
    client, backend, _ = adapter(request(), backend=SequenceBackend(stream))
    with pytest.raises(asyncio.CancelledError):
        await client.generate(request())
    assert len(backend.calls) == 1 and client.budget.records[0].usage.source == "unknown"
    assert stream.closed


def test_wire_projection_preserves_local_validation_and_uses_closed_objects():
    req = request(allowed_tools=["lookup_definition"], output_mode="native_json_schema")
    schema = wire_input(req).schema

    def check(value):
        if isinstance(value, dict):
            assert "oneOf" not in value and "discriminator" not in value
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value["properties"])
            for item in value.values():
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    check(schema)
    with pytest.raises(InvalidOutput):
        project_schema({"type": "object"})


def test_tool_replay_and_result_contract_additions_remain_bounded_and_secret_free():
    with pytest.raises(ValidationError):
        ToolExchange(
            action={"call_id": "c", "arguments": {"name": "lookup_definition", "term": "x"}},
            output_json='{"x":1,"x":2}',
        )
    with pytest.raises(ValidationError):
        GenerationResult(
            request_id=uid(1),
            status="completed",
            output_json="{}",
            provider_request_id="unsafe\nvalue",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize(
    "name,args",
    [
        ("search_document", {"query": "synthetic clause", "limit": 2}),
        ("read_section", {"section_id": "section-1", "cursor": 0}),
        ("read_chunk_neighbors", {"chunk_ids": [str(uid(14))], "radius": 1}),
        ("lookup_definition", {"term": "synthetic-term"}),
    ],
)
async def test_all_registered_tool_argument_schemas(provider, name, args):
    req = request(provider, native=True, allowed_tools=[name])
    client, _, _ = adapter(
        req, wire(reply(provider, status="tool_actions", tool=name, arguments=args))
    )
    result = await client.generate(req)
    assert result.status == "tool_actions" and result.actions[0].arguments.name == name


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [502, 503, 504])
async def test_transient_http_retries_require_explicit_policy_and_preserve_unknown_usage(status):
    req = request()
    failure = wire({}, status=f"{status} Transient".encode())
    client, backend, _ = adapter(req, failure, wire(reply("openai")), clock=FakeClock())
    assert (await client.generate(req)).status == "failed" and len(backend.calls) == 1
    client, backend, _ = adapter(
        req,
        failure,
        wire(reply("openai")),
        clock=FakeClock(),
        policy=AttemptPolicy(retry_statuses=(status,)),
    )
    result = await client.generate(req)
    assert result.status == "completed" and result.usage.source == "unknown"
    assert len(backend.calls) == 2


@pytest.mark.asyncio
async def test_connect_failure_before_submit_is_retryable_without_claiming_no_charge():
    client, backend, auth = adapter(
        request(), httpcore.ConnectError("synthetic"), wire(reply("openai")), clock=FakeClock()
    )
    result = await client.generate(request())
    assert result.status == "completed" and result.usage.source == "unknown"
    assert auth.prepares == 2 and len(backend.calls) == 2 and not client.budget.records[0].submitted


@pytest.mark.asyncio
async def test_deadline_expiration_during_a_response_does_not_publish_late_success():
    clock = FakeClock()

    async def advance(index):
        clock.now = 121.0

    backend = SequenceBackend(wire(reply("openai")), on_connect=advance)
    client, _, _ = adapter(request(), backend=backend, clock=clock)
    result = await client.generate(request())
    assert result.failure.code == "budget_exhausted" and result.output_json is None


@pytest.mark.asyncio
async def test_request_budget_also_bounds_a_stalled_retry_sleep():
    budget = CallBudget(max_calls=3, max_tokens=100000, total_seconds=0.2)
    client, backend, _ = adapter(
        request(),
        wire({}, status=b"429 Rate Limited"),
        budget=budget,
        policy=AttemptPolicy(base_delay_seconds=0.0, max_delay_seconds=0.0),
    )

    async def stall(delay):
        await asyncio.sleep(2)

    client._sleep = stall
    result = await client.generate(request())
    assert result.failure.code == "budget_exhausted" and len(backend.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "counts,code",
    [
        ({"input_tokens": 30000, "output_tokens": 5}, "context_overflow"),
        ({"input_tokens": 10, "output_tokens": 300}, "truncated"),
    ],
)
async def test_server_ignoring_token_ceilings_cannot_publish_output_or_receive_more_calls(
    counts, code
):
    client, backend, _ = adapter(request(), wire(reply("openai", counts=counts)))
    result = await client.generate(request())
    assert result.failure.code == code and result.output_json is None
    assert result.usage.source == "reported"
    assert (await client.generate(request())).failure.code == "budget_exhausted"
    assert len(backend.calls) == 1


@pytest.mark.asyncio
async def test_credential_scope_must_match_profile_before_any_dial():
    req = request()
    req = GenerationRequest.model_validate(
        {**req.model_dump(), "profile": {**req.profile.model_dump(), "tenant_id": uid(101)}}
    )
    client, backend, _ = adapter(req)
    result = await client.generate(req)
    assert result.failure.code == "configuration" and not backend.calls


@pytest.mark.asyncio
async def test_json_action_ids_and_replayed_ids_are_validated_before_use():
    req = request(allowed_tools=["lookup_definition"])
    data = {
        "kind": "tool_actions",
        "actions": [
            {"call_id": "unsafe\nvalue", "arguments": {"name": "lookup_definition", "term": "x"}}
        ],
    }
    client, _, _ = adapter(req, wire(reply("openai", data)))
    assert (await client.generate(req)).failure.code == "invalid_schema"
    req = GenerationRequest.model_validate(
        {**req.model_dump(), "tool_results": [{"action": data["actions"][0], "output_json": "{}"}]}
    )
    client, backend, _ = adapter(req)
    assert (await client.generate(req)).failure.code == "configuration" and not backend.calls


@pytest.mark.asyncio
async def test_no_response_can_reflect_a_credential_into_an_application_result():
    client, backend, _ = adapter(request(), wire(reply("openai", {"facts": [], "note": SENTINEL})))
    result = await client.generate(request())
    assert result.status == "failed" and SENTINEL not in result.model_dump_json()
    assert len(backend.calls) == 1


@pytest.mark.asyncio
async def test_format_repair_is_not_retried_after_a_transient_response():
    req = request()
    client, backend, _ = adapter(
        req,
        wire(reply("openai", "invalid")),
        wire({}, status=b"429 Rate Limited"),
        wire(reply("openai")),
        clock=FakeClock(),
    )
    result = await client.generate(req)
    assert result.status == "failed" and len(backend.calls) == 2
    assert sum(item.repair for item in client.budget.records) == 1


@pytest.mark.asyncio
async def test_one_format_repair_is_shared_across_distinct_task_request_ids():
    req = request()
    client, backend, _ = adapter(
        req,
        wire(reply("openai", "invalid")),
        wire(reply("openai")),
        wire(reply("openai", "invalid")),
    )
    assert (await client.generate(req)).status == "completed"
    next_req = req.model_copy(update={"request_id": uid(200)})
    assert (await client.generate(next_req)).failure.code == "budget_exhausted"
    assert len(backend.calls) == 3 and sum(item.repair for item in client.budget.records) == 1


def test_schema_projection_never_drops_properties_named_like_schema_keywords():
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "default": {"type": "number", "minimum": 0},
        },
    }
    actual = project_schema(schema)
    assert set(actual["properties"]) == {"title", "description", "default"}
    assert actual["properties"]["default"] == {"type": "number"}


@pytest.mark.asyncio
async def test_partial_native_tool_output_cannot_be_returned_as_an_action():
    req = request(native=True, allowed_tools=["lookup_definition"])
    data = reply("openai", status="tool_actions")
    data["output"][0]["status"] = "in_progress"
    client, backend, _ = adapter(req, wire(data))
    assert (await client.generate(req)).status == "truncated" and len(backend.calls) == 1


@pytest.mark.asyncio
async def test_retry_after_http_date_is_bounded_and_unknown_body_is_not_parsed():
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    date = format_datetime(datetime.now(UTC) + timedelta(seconds=3), usegmt=True).encode()
    clock = FakeClock()
    client, backend, _ = adapter(
        request(),
        wire({}, status=b"429 Rate Limited", headers=((b"Retry-After", date),)),
        wire(reply("openai")),
        clock=clock,
    )
    assert (await client.generate(request())).status == "completed"
    assert len(backend.calls) == 2 and 0 <= clock.sleeps[0] <= 3


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_hidden_reasoning_is_not_exported_or_replayed(provider):
    req = request(provider)
    data = reply(provider)
    marker = "synthetic-private-reasoning-must-be-discarded"
    if provider == "openai":
        data["output"].insert(0, {"type": "reasoning", "status": None, "summary": [marker]})
    elif provider == "anthropic":
        data["content"].insert(
            0, {"type": "thinking", "thinking": marker, "signature": "synthetic"}
        )
    else:
        data["choices"][0]["message"]["reasoning_content"] = marker
    client, backend, _ = adapter(req, wire(data))
    result = await client.generate(req)
    assert result.status == "completed"
    assert marker not in (
        result.model_dump_json()
        + json.dumps(backend.payload())
        + json.dumps([r.model_dump(mode="json") for r in client.budget.records])
    )


@pytest.mark.asyncio
async def test_invalid_application_input_is_a_safe_failure_without_validation_input_leaks():
    client, backend, _ = adapter(request())
    result = await client.generate({"request_id": "invalid", "api_key": SENTINEL})
    assert result.failure.code == "configuration"
    assert SENTINEL not in result.model_dump_json() and not backend.calls


def test_json_action_schema_exposes_only_the_request_allowlist():
    req = request(allowed_tools=["lookup_definition"], output_mode="native_json_schema")
    schema = wire_input(req).schema
    assert "LookupDefinition" in schema["$defs"] and "SearchDocument" not in schema["$defs"]


@pytest.mark.asyncio
async def test_current_credential_accidentally_placed_in_a_prompt_is_blocked_before_any_dial():
    req = request(messages=[{"role": "user", "content": "Synthetic accidental key: " + SENTINEL}])
    client, backend, _ = adapter(req)
    result = await client.generate(req)
    assert result.failure.code == "configuration" and not backend.calls
    assert SENTINEL not in result.model_dump_json()


def test_native_schema_projection_rejects_unchecked_external_references():
    with pytest.raises(InvalidOutput):
        project_schema({"$ref": "http://169.254.169.254/schema"})
