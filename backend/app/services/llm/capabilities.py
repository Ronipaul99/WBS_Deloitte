"""Opt-in synthetic probes and bounded model discovery. No capability promotion/storage."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from app.services.llm.adapter_types import AttemptRecord, BudgetExhausted, fingerprint
from app.services.llm.base import BaseProvider
from app.services.llm.contracts import (
    Contract,
    Count,
    FailureCode,
    Identity,
    Label,
    Positive,
    SafeFailure,
    Sha256,
    Support,
    Usage,
)
from app.services.llm.credentials import CredentialReceipt
from app.services.llm.errors import LlmSecurityError, SecurityCode
from app.services.llm.protocol_support import (
    DecodeScope,
    InvalidOutput,
    WireInput,
    compact,
    parse_json,
    project_schema,
    tool_schemas,
)
from app.services.llm.secure_transport import TransportFailure, TransportMetadata

ProbeCase = Literal[
    "authentication",
    "model_access",
    "structured_output",
    "native_tools",
    "token_limit",
    "usage",
    "temperature",
    "timeout",
]


class ProbePlan(Contract):
    cases: Annotated[tuple[ProbeCase, ...], Field(min_length=1, max_length=8)] = (
        "authentication",
        "model_access",
        "structured_output",
        "usage",
    )
    input_token_ceiling: Annotated[int, Field(strict=True, ge=512, le=8192)] = 4096
    max_output_tokens: Annotated[int, Field(strict=True, ge=8, le=256)] = 128
    timeout_seconds: Annotated[float, Field(gt=0, le=30)] = 10.0

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.cases)) != len(self.cases):
            raise ValueError("duplicate probe case")
        return self


class LiveProbePermit(Contract):
    """Separately authorized server context. Never obtain this from model/user JSON.

    Required for real-network probes, even when runtime credentials are present.
    No permit is provisioned by this implementation.
    """

    connection_id: Identity
    expires_at: datetime
    max_calls: Annotated[int, Field(strict=True, ge=1, le=9)]
    max_tokens: Positive
    configuration_fingerprint: Sha256
    max_cost_usd: Annotated[Decimal, Field(ge=0, le=100)]
    input_usd_per_million: Annotated[Decimal, Field(ge=0, le=100_000)]
    output_usd_per_million: Annotated[Decimal, Field(ge=0, le=100_000)]
    request_fee_usd: Annotated[Decimal, Field(ge=0, le=100)]
    pricing_reviewed_at: datetime
    approved_synthetic_only: Literal[True]

    @model_validator(mode="after")
    def aware(self):
        if self.expires_at.utcoffset() is None or self.pricing_reviewed_at.utcoffset() is None:
            raise ValueError("permit expiry requires aware time")
        return self


class ProbeSettings(Contract):
    input_token_ceiling: Positive
    max_output_tokens: Positive
    timeout_seconds: Annotated[float, Field(gt=0, le=30)]
    effective_timeout_seconds: Annotated[float, Field(gt=0, le=30)]
    temperature: Annotated[float, Field(ge=0, le=1)] | None = None


class ProbeObservation(Contract):
    observation_id: Identity
    checked_at: datetime
    connection_id: Identity
    profile_id: Identity
    profile_version: Positive
    configuration_fingerprint: Sha256
    origin: Literal["synthetic_fixture", "live_network"]
    case: ProbeCase
    settings: ProbeSettings
    support: Support
    outcome: Literal[
        "completed", "tool_actions", "refused", "truncated", "failed", "invalid", "timeout"
    ]
    elapsed_ms: Count
    receipt: CredentialReceipt | None = None
    usage: Usage = Field(default_factory=Usage)
    provider_request_id: (
        Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")] | None
    ) = None
    failure: SafeFailure | None = None


class CapabilityReport(Contract):
    """Observations only; deliberately NOT ProviderCapabilities or an enabled profile."""

    observations: Annotated[tuple[ProbeObservation, ...], Field(min_length=1, max_length=8)]

    def is_current(self, profile, pinned, options, plan: ProbePlan):
        current = fingerprint(profile, pinned, options, include_capabilities=False)
        return {item.case for item in self.observations} == set(plan.cases) and all(
            item.configuration_fingerprint == current
            and item.settings.input_token_ceiling == plan.input_token_ceiling
            and item.settings.max_output_tokens
            == (8 if item.case == "token_limit" else plan.max_output_tokens)
            and item.settings.timeout_seconds == plan.timeout_seconds
            for item in self.observations
        )


class ModelListReport(Contract):
    status: Literal["completed", "unavailable"]
    model_ids: Annotated[tuple[Label, ...], Field(max_length=1000)] = ()
    partial: bool = False
    receipt: CredentialReceipt | None = None
    failure: SafeFailure | None = None


class _ProbeAnswer(Contract):
    answer: Literal["synthetic-ok"]


class CapabilityProber:
    def __init__(self, provider: BaseProvider, *, permit: LiveProbePermit | None = None):
        self.provider = provider
        self.permit = permit

    def _authorize(self):
        provider = self.provider
        provider._check_binding(provider.profile, inference=False)
        if provider.transport.execution_origin != "synthetic_fixture":
            permit = self.permit
            if (
                permit is None
                or permit.connection_id != provider.profile.connection_id
                or permit.expires_at <= datetime.now(UTC)
                or provider.budget.max_calls > permit.max_calls
                or provider.budget.max_tokens > permit.max_tokens
                or permit.configuration_fingerprint
                != fingerprint(
                    provider.profile, provider.pinned, provider.options, include_capabilities=False
                )
                or (
                    Decimal(provider.budget.max_tokens)
                    * max(permit.input_usd_per_million, permit.output_usd_per_million)
                    / Decimal(1_000_000)
                    + Decimal(provider.budget.max_calls) * permit.request_fee_usd
                    > permit.max_cost_usd
                )
            ):
                raise InvalidOutput()

    async def run(self, plan: ProbePlan) -> CapabilityReport:
        async with self.provider.budget.lock:
            self._authorize()
            results = []
            for case in plan.cases:
                # Expiry/revocation authorization is checked for each new request.
                self._authorize()
                results.append(await self._probe(case, plan))
            return CapabilityReport(observations=tuple(results))

    async def _probe(self, case, plan):
        provider = self.provider
        identity = uuid4()
        max_output = 8 if case == "token_limit" else plan.max_output_tokens
        tools = tuple(tool_schemas(("lookup_definition",))) if case == "native_tools" else ()
        instruction = (
            'Call lookup_definition with term "synthetic-term". Do not answer directly.'
            if tools
            else 'Return only JSON {"schema_version":"1.0","answer":"synthetic-ok"}.'
        )
        if case == "token_limit":
            instruction = "Return a JSON object containing the word synthetic repeated 100 times."
        wire = WireInput(
            provider.profile.model_id,
            "This is a synthetic protocol qualification probe.",
            ({"role": "user", "content": instruction},),
            max_output,
            0.0 if case == "temperature" else None,
            project_schema(_ProbeAnswer.model_json_schema())
            if case == "structured_output"
            else None,
            tools,
            (),
        )
        payload = provider.encode(wire)
        if len(compact(payload).encode()) + 256 > plan.input_token_ceiling:
            raise BudgetExhausted()
        sequence = await provider.budget.before_attempt(plan.input_token_ceiling, max_output)
        started = provider.budget._clock()
        effective_timeout = min(
            plan.timeout_seconds,
            provider.profile.timeout_seconds,
            provider.budget.remaining_seconds,
        )
        if effective_timeout <= 0:
            raise BudgetExhausted()
        origin = provider.transport.execution_origin
        counts, receipt, external_id = Usage(), None, None
        outcome, support, failure = "failed", Support.UNKNOWN, None
        submitted, http_status = False, None
        try:
            response = await provider.transport.send(
                connection_id=provider.profile.connection_id,
                pinned=provider.pinned,
                url=provider.url,
                purpose="test",
                payload=payload,
                advanced_headers=provider.headers,
                expected_tenant_id=provider.profile.tenant_id,
                timeout_seconds=effective_timeout,
            )
            receipt, submitted, http_status = response.receipt, True, response.status
            parsed = provider.decode(
                DecodeScope(
                    provider.profile.model_id, ("lookup_definition",) if tools else (), bool(tools)
                ),
                response,
            )
            outcome, counts, external_id = parsed.status, parsed.usage, parsed.provider_request_id
            failure = parsed.failure
            if case == "native_tools":
                success = (
                    outcome == "tool_actions"
                    and len(parsed.actions) == 1
                    and parsed.actions[0].arguments.name == "lookup_definition"
                    and parsed.actions[0].arguments.term == "synthetic-term"
                )
                support = Support.SUPPORTED if success else Support.UNKNOWN
            elif case == "usage":
                support = Support.SUPPORTED if counts.source == "reported" else Support.UNKNOWN
            elif case == "token_limit":
                if outcome == "truncated" or (
                    counts.source == "reported" and counts.output_tokens <= max_output
                ):
                    support = Support.SUPPORTED
            elif outcome == "completed":
                _ProbeAnswer.model_validate(parse_json(parsed.text))
                support = Support.SUPPORTED
                if (
                    case == "model_access"
                    and response.data.get("model") != provider.profile.model_id
                ):
                    support = Support.UNKNOWN
            if provider.budget.remaining_seconds <= 0:
                outcome, support, failure = (
                    "timeout",
                    Support.UNKNOWN,
                    FailureCode.PROVIDER_UNAVAILABLE,
                )
            if counts.source == "reported" and (
                counts.input_tokens > plan.input_token_ceiling or counts.output_tokens > max_output
            ):
                await provider.budget.after_overrun(
                    counts.input_tokens
                    + counts.output_tokens
                    - plan.input_token_ceiling
                    - max_output
                )
                support, outcome, failure = Support.UNSUPPORTED, "truncated", FailureCode.TRUNCATED
        except asyncio.CancelledError:
            await provider.budget.after_attempt(
                AttemptRecord(
                    request_id=identity,
                    sequence=sequence,
                    purpose="test",
                    outcome="failed",
                    submitted=True,
                    stop_reason="error",
                    failure=FailureCode.CANCELLED,
                )
            )
            raise
        except LlmSecurityError as error:
            meta = error.metadata if isinstance(error, TransportFailure) else TransportMetadata()
            receipt, submitted, http_status, external_id = (
                meta.receipt,
                meta.submitted,
                meta.http_status,
                meta.provider_request_id,
            )
            outcome = "timeout" if error.code == SecurityCode.TIMEOUT else "failed"
            failure = FailureCode.PROVIDER_UNAVAILABLE
            if case == "authentication" and http_status in {401, 403}:
                support = Support.UNSUPPORTED
                failure = FailureCode.CONFIGURATION
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError, InvalidOutput):
            outcome, failure = "invalid", FailureCode.INVALID_SCHEMA
        elapsed = min(10_000_000, max(0, int((provider.budget._clock() - started) * 1000)))
        observation = ProbeObservation(
            observation_id=identity,
            checked_at=datetime.now(UTC),
            connection_id=provider.profile.connection_id,
            profile_id=provider.profile.profile_id,
            profile_version=provider.profile.profile_version,
            configuration_fingerprint=fingerprint(
                provider.profile, provider.pinned, provider.options, include_capabilities=False
            ),
            origin=origin,
            case=case,
            settings=ProbeSettings(
                input_token_ceiling=plan.input_token_ceiling,
                max_output_tokens=max_output,
                timeout_seconds=plan.timeout_seconds,
                effective_timeout_seconds=effective_timeout,
                temperature=wire.temperature,
            ),
            support=support,
            outcome=outcome,
            elapsed_ms=elapsed,
            receipt=receipt,
            usage=counts,
            provider_request_id=external_id,
            failure=SafeFailure(code=failure, correlation_id=uuid4()) if failure else None,
        )
        await provider.budget.after_attempt(
            AttemptRecord(
                request_id=identity,
                sequence=sequence,
                purpose="test",
                outcome="failed" if outcome == "timeout" else outcome,
                receipt=receipt,
                submitted=submitted,
                http_status=http_status,
                provider_request_id=external_id,
                usage=counts,
                stop_reason={
                    "completed": "stop",
                    "tool_actions": "tools",
                    "refused": "refusal",
                    "truncated": "length",
                }.get(outcome, "error"),
                failure=failure,
            )
        )
        return observation

    async def list_models(self) -> ModelListReport:
        """One bounded page only. Never follow returned URLs or infer inference failure."""
        provider = self.provider
        async with provider.budget.lock:
            self._authorize()
            sequence = await provider.budget.before_attempt(1, 1)
            identity, receipt, external_id = uuid4(), None, None
            failure, model_ids, partial, submitted, status = None, (), False, False, None
            try:
                prefix = provider.pinned.approval.path_prefix.rstrip("/")
                response = await provider.transport.send(
                    connection_id=provider.profile.connection_id,
                    pinned=provider.pinned,
                    url=provider.pinned.base_url + prefix + "/models",
                    purpose="discovery",
                    method="GET",
                    advanced_headers=provider.headers,
                    expected_tenant_id=provider.profile.tenant_id,
                    timeout_seconds=min(10.0, provider.budget.remaining_seconds),
                )
                receipt, external_id, submitted, status = (
                    response.receipt,
                    response.provider_request_id,
                    True,
                    response.status,
                )
                values = response.data.get("data") if isinstance(response.data, dict) else None
                if not isinstance(values, list) or len(values) > 1000:
                    raise InvalidOutput()
                model_ids = tuple(dict.fromkeys(item["id"] for item in values))
                partial = response.data.get("has_more", False)
                if type(partial) is not bool:
                    raise InvalidOutput()
                partial = partial or any(
                    response.data.get(key) for key in ("next", "next_url", "next_page")
                )
                report = ModelListReport(
                    status="completed", model_ids=model_ids, partial=partial, receipt=receipt
                )
            except LlmSecurityError as error:
                metadata = (
                    error.metadata if isinstance(error, TransportFailure) else TransportMetadata()
                )
                receipt, external_id, submitted, status = (
                    metadata.receipt,
                    metadata.provider_request_id,
                    metadata.submitted,
                    metadata.http_status,
                )
                failure = FailureCode.PROVIDER_UNAVAILABLE
            except (ValueError, TypeError, KeyError, AttributeError, InvalidOutput):
                failure = FailureCode.INVALID_SCHEMA
            if failure:
                report = ModelListReport(
                    status="unavailable",
                    receipt=receipt,
                    failure=SafeFailure(code=failure, correlation_id=uuid4()),
                )
            await provider.budget.after_attempt(
                AttemptRecord(
                    request_id=identity,
                    sequence=sequence,
                    purpose="discovery",
                    outcome="failed" if failure else "completed",
                    receipt=receipt,
                    submitted=submitted,
                    http_status=status,
                    provider_request_id=external_id,
                    stop_reason="error" if failure else "stop",
                    failure=failure,
                )
            )
            return report
