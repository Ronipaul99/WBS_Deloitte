"""Qualification primitives use synthetic answers through the checked fake wire only."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpcore
import pytest
from agent_schema_fixtures import uid
from llm_adapter_fixtures import PROVIDERS, SequenceBackend, adapter, reply, request, wire
from llm_security_fixtures import FakeAuthorizer, FakeStream
from pydantic import ValidationError

from app.services.llm.adapter_types import AdapterOptions, BudgetExhausted, CallBudget, fingerprint
from app.services.llm.capabilities import CapabilityProber, LiveProbePermit, ProbePlan
from app.services.llm.contracts import ModelProfileSnapshot
from app.services.llm.protocol_support import InvalidOutput
from app.services.llm.secure_transport import SecureJsonTransport


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize(
    "case", ["authentication", "model_access", "structured_output", "usage", "temperature"]
)
async def test_opt_in_synthetic_probes_record_the_exact_configuration_without_enabling(
    provider, case
):
    req = request(provider)
    client, backend, _ = adapter(req, wire(reply(provider, {"answer": "synthetic-ok"})))
    report = await CapabilityProber(client).run(ProbePlan(cases=(case,)))
    observation = report.observations[0]
    assert observation.support == "supported" and observation.origin == "synthetic_fixture"
    assert observation.profile_id == req.profile.profile_id and observation.profile_version == 1
    assert (
        observation.connection_id == req.profile.connection_id
        and observation.receipt.credential_version == 1
    )
    assert (
        observation.checked_at.tzinfo is not None
        and observation.provider_request_id == "req_synthetic"
    )
    assert (
        client.profile.enabled is False
        and client.profile.capabilities.qualification == "synthetic_fixture"
    )
    assert report.is_current(req.profile, client.pinned, client.options, ProbePlan(cases=(case,)))
    payload = backend.payload()
    assert "synthetic" in json.dumps(payload) and req.messages[0].content not in json.dumps(payload)
    assert not hasattr(report, "enabled") and not hasattr(report, "capabilities")


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_native_tool_probe_does_not_invent_capabilities_to_bootstrap(provider):
    req = request(provider)
    assert req.profile.capabilities.native_tools == "unknown"
    client, _, _ = adapter(req, wire(reply(provider, status="tool_actions")))
    report = await CapabilityProber(client).run(ProbePlan(cases=("native_tools",)))
    assert report.observations[0].support == "supported"
    assert client.profile.capabilities.native_tools == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_pending_profile_can_be_probed_without_making_up_qualified_limits(provider):
    req = request(provider)
    client, backend, _ = adapter(req, wire(reply(provider, {"answer": "synthetic-ok"})))
    client.profile = ModelProfileSnapshot.model_validate(
        {**req.profile.model_dump(), "capabilities": {}}
    )
    report = await CapabilityProber(client).run(ProbePlan(cases=("model_access",)))
    assert report.observations[0].support == "supported"
    assert client.profile.capabilities.qualification == "pending"
    assert client.profile.capabilities.context_tokens is None and not client.profile.enabled
    assert len(backend.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_token_limit_probe_records_only_the_observed_small_output_bound(provider):
    req = request(provider)
    client, backend, _ = adapter(req, wire(reply(provider, status="truncated")))
    report = await CapabilityProber(client).run(ProbePlan(cases=("token_limit",)))
    assert (
        report.observations[0].support == "supported"
        and report.observations[0].outcome == "truncated"
    )
    payload = backend.payload()
    assert payload.get("max_output_tokens", payload.get("max_tokens")) == 8
    assert not hasattr(report.observations[0], "context_tokens")


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_missing_usage_is_inconclusive_and_not_enabled(provider):
    req = request(provider)
    client, _, _ = adapter(req, wire(reply(provider, {"answer": "synthetic-ok"}, counts=None)))
    observation = (await CapabilityProber(client).run(ProbePlan(cases=("usage",)))).observations[0]
    assert observation.support == "unknown" and observation.usage.source == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("model_id", "different"), ("profile_version", 2), ("timeout_seconds", 30)]
)
async def test_model_profile_or_relevant_setting_change_invalidates_observations(field, value):
    req = request()
    client, _, _ = adapter(req, wire(reply("openai", {"answer": "synthetic-ok"})))
    report = await CapabilityProber(client).run(ProbePlan(cases=("model_access",)))
    changed = ModelProfileSnapshot.model_validate({**req.profile.model_dump(), field: value})
    assert not report.is_current(
        changed, client.pinned, client.options, ProbePlan(cases=("model_access",))
    )


@pytest.mark.asyncio
async def test_endpoint_auth_or_token_dialect_change_invalidates_observations():
    req = request("openai_compatible")
    client, _, _ = adapter(req, wire(reply("openai_compatible", {"answer": "synthetic-ok"})))
    report = await CapabilityProber(client).run(ProbePlan(cases=("structured_output",)))
    assert not report.is_current(
        req.profile,
        client.pinned,
        AdapterOptions(compatible_token_parameter="max_completion_tokens"),
        ProbePlan(cases=("structured_output",)),
    )
    changed = type(client.pinned)(client.pinned.approval.model_copy(update={"path_prefix": "/v2"}))
    assert not report.is_current(
        req.profile, changed, client.options, ProbePlan(cases=("structured_output",))
    )


@pytest.mark.asyncio
async def test_missing_model_list_does_not_imply_inference_unavailable_and_manual_id_stays():
    req = request()
    client, backend, _ = adapter(req, wire({}, status=b"404 Not Found"), wire(reply("openai")))
    report = await CapabilityProber(client).list_models()
    assert report.status == "unavailable" and not report.model_ids
    assert (await client.generate(req)).status == "completed"
    assert client.profile.model_id == req.profile.model_id and len(backend.calls) == 2
    assert client.budget.records[0].purpose == "discovery"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_model_list_is_one_bounded_page_and_never_follows_next_urls(provider):
    req = request(provider)
    client, backend, _ = adapter(
        req,
        wire(
            {
                "data": [{"id": "synthetic-model"}],
                "has_more": True,
                "next": "http://169.254.169.254/",
            }
        ),
    )
    report = await CapabilityProber(client).list_models()
    assert (
        report.status == "completed" and report.partial and report.model_ids == ("synthetic-model",)
    )
    assert len(backend.calls) == 1 and report.receipt.purpose == "discovery"


@pytest.mark.asyncio
async def test_overlong_model_list_and_malformed_model_ids_are_rejected():
    for data in (
        {"data": [{"id": "x"}] * 1001},
        {"data": [{"id": "x" * 161}]},
        {"data": [{"id": False}]},
        {"data": {}, "has_more": True},
    ):
        client, _, _ = adapter(request(), wire(data))
        report = await CapabilityProber(client).list_models()
        assert report.status == "unavailable" and report.failure.code == "invalid_schema"


@pytest.mark.asyncio
async def test_probe_timeout_has_unknown_usage_and_fresh_metadata():
    stream = FakeStream(b"")

    async def timeout(*args, **kwargs):
        raise httpcore.ReadTimeout("synthetic")

    stream.read = timeout
    client, _, _ = adapter(request(), backend=SequenceBackend(stream))
    observation = (await CapabilityProber(client).run(ProbePlan(cases=("timeout",)))).observations[
        0
    ]
    assert observation.outcome == "timeout" and observation.support == "unknown"
    assert observation.usage.source == "unknown" and observation.receipt.credential_version == 1


@pytest.mark.asyncio
async def test_each_probe_consumes_shared_budget_and_unauthorized_live_probe_fails_closed():
    budget = CallBudget(max_calls=1, max_tokens=100000, total_seconds=10)
    client, backend, _ = adapter(
        request(), wire(reply("openai", {"answer": "synthetic-ok"})), budget=budget
    )
    with pytest.raises(BudgetExhausted):
        await CapabilityProber(client).run(ProbePlan(cases=("authentication", "model_access")))
    assert len(backend.calls) == 1
    client, _, _ = adapter(request())
    client.transport = SecureJsonTransport(client.transport._endpoints, FakeAuthorizer())
    with pytest.raises(InvalidOutput):
        await CapabilityProber(client).run(ProbePlan(cases=("authentication",)))
    assert client.budget.calls == 0


@pytest.mark.asyncio
async def test_expired_or_wrong_connection_live_permit_does_not_send():
    for connection in (uid(5), uid(500)):
        client, _, _ = adapter(request())
        client.transport = SecureJsonTransport(client.transport._endpoints, FakeAuthorizer())
        permit = LiveProbePermit(
            connection_id=connection,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
            max_calls=8,
            max_tokens=100000,
            approved_synthetic_only=True,
            configuration_fingerprint=fingerprint(
                client.profile, client.pinned, client.options, include_capabilities=False
            ),
            max_cost_usd="1",
            input_usd_per_million="1",
            output_usd_per_million="1",
            request_fee_usd="0",
            pricing_reviewed_at=datetime.now(UTC),
        )
        with pytest.raises(InvalidOutput):
            await CapabilityProber(client, permit=permit).list_models()
        assert client.budget.calls == 0


@pytest.mark.asyncio
async def test_failed_authentication_does_not_publish_other_capabilities():
    client, backend, _ = adapter(request(), wire({}, status=b"401 Unauthorized"))
    report = await CapabilityProber(client).run(ProbePlan(cases=("authentication",)))
    assert report.observations[0].support == "unsupported"
    assert len(backend.calls) == 1 and client.profile.enabled is False


@pytest.mark.parametrize(
    "change",
    [
        {"cases": []},
        {"cases": ["shell"]},
        {"cases": ["usage", "usage"]},
        {"max_output_tokens": 5000},
        {"input_token_ceiling": True},
        {"timeout_seconds": float("nan")},
    ],
)
def test_probe_plan_rejects_unbounded_or_arbitrary_inputs(change):
    with pytest.raises(ValidationError):
        ProbePlan.model_validate(change)


@pytest.mark.asyncio
async def test_probe_cancellation_propagates_and_is_not_capability_success():
    stream = FakeStream(b"")

    async def cancel(*args, **kwargs):
        raise asyncio.CancelledError()

    stream.read = cancel
    client, backend, _ = adapter(request(), backend=SequenceBackend(stream))
    with pytest.raises(asyncio.CancelledError):
        await CapabilityProber(client).run(ProbePlan(cases=("authentication",)))
    assert len(backend.calls) == 1 and client.budget.records[0].failure == "cancelled"


@pytest.mark.asyncio
async def test_changed_probe_limits_invalidate_previous_observations():
    req = request()
    client, _, _ = adapter(req, wire(reply("openai", {"answer": "synthetic-ok"})))
    plan = ProbePlan(cases=("structured_output",))
    report = await CapabilityProber(client).run(plan)
    assert report.observations[0].settings.max_output_tokens == 128
    assert not report.is_current(
        req.profile,
        client.pinned,
        client.options,
        ProbePlan(cases=("structured_output",), max_output_tokens=64),
    )
    assert not report.is_current(
        req.profile,
        client.pinned,
        client.options,
        ProbePlan(cases=("structured_output",), timeout_seconds=5.0),
    )


@pytest.mark.asyncio
async def test_probe_server_ignoring_the_small_token_limit_is_not_qualified():
    req = request()
    client, backend, _ = adapter(
        req,
        wire(
            reply(
                "openai",
                {"answer": "synthetic-ok"},
                counts={"input_tokens": 10, "output_tokens": 200},
            )
        ),
    )
    report = await CapabilityProber(client).run(ProbePlan(cases=("token_limit",)))
    observation = report.observations[0]
    assert observation.support == "unsupported" and observation.failure.code == "truncated"
    with pytest.raises(BudgetExhausted):
        await CapabilityProber(client).list_models()
    assert len(backend.calls) == 1


@pytest.mark.asyncio
async def test_live_probe_cost_ceiling_is_explicitly_required_and_checked_before_network():
    client, _, _ = adapter(request())
    client.transport = SecureJsonTransport(client.transport._endpoints, FakeAuthorizer())
    permit = LiveProbePermit(
        connection_id=client.profile.connection_id,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
        max_calls=8,
        max_tokens=100000,
        approved_synthetic_only=True,
        configuration_fingerprint=fingerprint(
            client.profile, client.pinned, client.options, include_capabilities=False
        ),
        max_cost_usd="0.01",
        input_usd_per_million="100",
        output_usd_per_million="100",
        request_fee_usd="0",
        pricing_reviewed_at=datetime.now(UTC),
    )
    with pytest.raises(InvalidOutput):
        await CapabilityProber(client, permit=permit).list_models()
    assert client.budget.calls == 0


@pytest.mark.asyncio
async def test_an_answer_without_model_identity_cannot_attest_exact_model_access():
    data = reply("openai", {"answer": "synthetic-ok"})
    data.pop("model")
    client, _, _ = adapter(request(), wire(data))
    report = await CapabilityProber(client).run(ProbePlan(cases=("model_access",)))
    assert report.observations[0].support == "unknown"
