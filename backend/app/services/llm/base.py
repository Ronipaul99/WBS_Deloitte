"""GenerationProvider implementation foundation; in-process budgets, no workflow executor."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from app.services.llm.adapter_types import (
    AdapterOptions,
    AttemptPolicy,
    AttemptRecord,
    BudgetExhausted,
    CallBudget,
    QualificationBinding,
    fingerprint,
)
from app.services.llm.contracts import (
    FailureCode,
    GenerationRequest,
    GenerationResult,
    ModelProfileSnapshot,
    SafeFailure,
    validate_result_binding,
)
from app.services.llm.endpoint_policy import PinnedEndpoint
from app.services.llm.errors import LlmSecurityError, SecurityCode
from app.services.llm.protocol_support import (
    InvalidOutput,
    compact,
    usage,
    validated_output,
    wire_input,
)
from app.services.llm.secure_transport import (
    SecureJsonTransport,
    TransportFailure,
    TransportMetadata,
)


class BaseProvider:
    """Implements the existing structural GenerationProvider protocol.

    Caller creates a trusted binding from qualified persisted metadata, then supplies
    one shared CallBudget. This class never enables or persists a profile.
    """

    provider = None
    protocol = None
    suffix = None
    authentication = ()

    def __init__(
        self,
        transport: SecureJsonTransport,
        profile: ModelProfileSnapshot,
        pinned: PinnedEndpoint,
        budget: CallBudget,
        *,
        qualification: QualificationBinding | None = None,
        options: AdapterOptions | None = None,
        policy: AttemptPolicy | None = None,
        sleep=None,
    ):
        if not isinstance(transport, SecureJsonTransport) or not isinstance(budget, CallBudget):
            raise ValueError("approved transport and caller-owned budget required")
        self.transport = transport
        self.profile = ModelProfileSnapshot.model_validate(profile)
        self.pinned = pinned
        self.budget = budget
        self.qualification = qualification
        self.options = options if options is not None else AdapterOptions()
        self.policy = policy if policy is not None else AttemptPolicy()
        self._sleep = sleep or asyncio.sleep

    @property
    def url(self):
        prefix = self.pinned.approval.path_prefix.rstrip("/")
        return self.pinned.base_url + prefix + self.suffix

    @property
    def headers(self):
        return ()

    def _check_binding(self, profile, *, inference):
        if (
            profile != self.profile
            or profile.provider != self.provider
            or profile.protocol != self.protocol
            or self.pinned.approval.auth_scheme not in self.authentication
            or self.budget.max_calls > profile.max_calls
            or self.budget.max_tokens > profile.max_total_tokens
        ):
            raise InvalidOutput()
        if self.provider != "openai_compatible" and self.options != AdapterOptions():
            raise InvalidOutput()
        if inference:
            if self.qualification is None or not self.qualification.matches(
                profile, self.pinned, self.options
            ):
                raise InvalidOutput()
            if self.transport.execution_origin == "synthetic_fixture":
                if profile.capabilities.qualification != "synthetic_fixture":
                    raise InvalidOutput()
            elif not profile.enabled or profile.capabilities.qualification != "live_worker":
                raise InvalidOutput()
        self.budget.validate_provider(profile, self.pinned, self.options)
        self.budget.bind(fingerprint(profile, self.pinned, self.options))

    def encode(self, wire):
        raise NotImplementedError()

    def decode(self, request, response):
        raise NotImplementedError()

    def _failure(self, request, code, start, provider_request_id=None):
        identity = getattr(request, "request_id", None)
        if not isinstance(identity, UUID) or identity.int == 0:
            identity = uuid4()
        return GenerationResult(
            request_id=identity,
            status="failed",
            failure=SafeFailure(code=code, correlation_id=uuid4()),
            usage=self.budget.usage_since(start),
            provider_request_id=provider_request_id,
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        async with self.budget.lock:
            start = len(self.budget.records)
            try:
                request = GenerationRequest.model_validate(request)
                self._check_binding(request.profile, inference=True)
                return await self._generate(request, start)
            except BudgetExhausted:
                return self._failure(request, FailureCode.BUDGET_EXHAUSTED, start)
            except (ValueError, TypeError, KeyError, AttributeError, InvalidOutput, RecursionError):
                return self._failure(request, FailureCode.CONFIGURATION, start)

    async def _generate(self, request, start):
        repair = False
        for local_attempt in range(self.policy.max_attempts):
            wire = wire_input(request, repair)
            payload = self.encode(wire)
            # Conservative, documented byte allowance includes schema/history/instructions.
            # It is NOT reported usage or proof of a particular gateway's tokenizer.
            if len(compact(payload).encode("utf-8")) + 256 > request.input_token_budget:
                return self._failure(request, FailureCode.CONTEXT_OVERFLOW, start)
            sequence = await self.budget.before_attempt(
                request.input_token_budget, request.max_output_tokens
            )
            response = None
            metadata = TransportMetadata()
            try:
                response = await self.transport.send(
                    connection_id=request.profile.connection_id,
                    pinned=self.pinned,
                    url=self.url,
                    purpose="inference",
                    payload=payload,
                    advanced_headers=self.headers,
                    expected_tenant_id=request.profile.tenant_id,
                    timeout_seconds=min(
                        request.profile.timeout_seconds, self.budget.remaining_seconds
                    ),
                )
            except asyncio.CancelledError:
                await self.budget.after_attempt(
                    AttemptRecord(
                        request_id=request.request_id,
                        sequence=sequence,
                        purpose="inference",
                        outcome="failed",
                        repair=repair,
                        submitted=True,
                        stop_reason="error",
                        failure=FailureCode.CANCELLED,
                    )
                )
                raise
            except LlmSecurityError as error:
                if isinstance(error, TransportFailure):
                    metadata = error.metadata
                code = (
                    FailureCode.CONFIGURATION
                    if metadata.http_status in {400, 401, 403, 404, 422}
                    or error.code
                    in {
                        SecurityCode.ACCESS_DENIED,
                        SecurityCode.CONNECTION_DISABLED,
                        SecurityCode.CREDENTIAL_CHANGED,
                        SecurityCode.CREDENTIAL_UNAVAILABLE,
                        SecurityCode.CREDENTIAL_INVALID,
                        SecurityCode.KEY_CONFIGURATION,
                        SecurityCode.ENDPOINT_DENIED,
                        SecurityCode.DNS_DENIED,
                        SecurityCode.DESTINATION_DENIED,
                        SecurityCode.TRANSPORT_UNSUPPORTED,
                    }
                    else FailureCode.PROVIDER_UNAVAILABLE
                )
                await self.budget.after_attempt(
                    AttemptRecord(
                        request_id=request.request_id,
                        sequence=sequence,
                        purpose="inference",
                        outcome="failed",
                        repair=repair,
                        receipt=metadata.receipt,
                        submitted=metadata.submitted,
                        http_status=metadata.http_status,
                        provider_request_id=metadata.provider_request_id,
                        stop_reason="error",
                        failure=code,
                    )
                )
                retry = metadata.http_status in self.policy.retry_statuses or (
                    error.code in {SecurityCode.TIMEOUT, SecurityCode.TRANSPORT_FAILED}
                    and (
                        self.policy.retry_ambiguous_submission
                        if metadata.submitted
                        else self.policy.retry_before_submit
                    )
                )
                if retry and not repair and local_attempt + 1 < self.policy.max_attempts:
                    delay = (
                        metadata.retry_after_seconds
                        if metadata.retry_after_seconds is not None
                        else self.policy.base_delay_seconds * 2**local_attempt
                    )
                    if delay > self.policy.max_delay_seconds:
                        return self._failure(request, code, start, metadata.provider_request_id)
                    if delay >= self.budget.remaining_seconds:
                        raise BudgetExhausted() from None
                    try:
                        async with asyncio.timeout(self.budget.remaining_seconds):
                            await self._sleep(delay)
                    except TimeoutError:
                        raise BudgetExhausted() from None
                    continue
                return self._failure(request, code, start, metadata.provider_request_id)
            outcome = None
            try:
                outcome = self.decode(request, response)
                if outcome.usage.source == "reported" and (
                    outcome.usage.input_tokens > request.input_token_budget
                    or outcome.usage.output_tokens > request.max_output_tokens
                ):
                    await self.budget.after_overrun(
                        outcome.usage.input_tokens
                        + outcome.usage.output_tokens
                        - request.input_token_budget
                        - request.max_output_tokens
                    )
                    # The server did not respect the admitted ceilings. Keep usage, no output.
                    outcome = type(outcome)(
                        "failed"
                        if outcome.usage.input_tokens > request.input_token_budget
                        else "truncated",
                        outcome.usage,
                        outcome.provider_request_id,
                        failure=(
                            FailureCode.CONTEXT_OVERFLOW
                            if outcome.usage.input_tokens > request.input_token_budget
                            else FailureCode.TRUNCATED
                        ),
                    )
                output_json, actions = None, outcome.actions
                if outcome.status == "completed":
                    output_json, actions = validated_output(request, outcome.text)
                status = "tool_actions" if actions else outcome.status
                result = GenerationResult(
                    request_id=request.request_id,
                    status=status,
                    output_json=output_json,
                    actions=actions,
                    usage=outcome.usage,
                    provider_request_id=outcome.provider_request_id,
                    failure=(
                        SafeFailure(code=outcome.failure, correlation_id=uuid4())
                        if outcome.failure is not None
                        else None
                    ),
                )
                validate_result_binding(request, result)
            except (ValueError, TypeError, KeyError, AttributeError, InvalidOutput, RecursionError):
                # Malformed output is not echoed to the repair prompt or logs.
                await self.budget.after_attempt(
                    AttemptRecord(
                        request_id=request.request_id,
                        sequence=sequence,
                        purpose="inference",
                        outcome="invalid",
                        repair=repair,
                        receipt=response.receipt,
                        submitted=True,
                        http_status=response.status,
                        provider_request_id=response.provider_request_id,
                        stop_reason="error",
                        usage=(
                            outcome.usage
                            if outcome is not None
                            else usage(
                                response.data.get("usage")
                                if isinstance(response.data, dict)
                                else None,
                                {
                                    "openai": "responses",
                                    "anthropic": "anthropic",
                                    "openai_compatible": "chat",
                                }[request.profile.provider],
                            )
                        ),
                        failure=FailureCode.INVALID_SCHEMA,
                    )
                )
                if (
                    self.policy.allow_format_repair
                    and not repair
                    and local_attempt + 1 < self.policy.max_attempts
                ):
                    await self.budget.before_repair(request.request_id)
                    repair = True
                    continue
                return self._failure(
                    request, FailureCode.INVALID_SCHEMA, start, response.provider_request_id
                )
            await self.budget.after_attempt(
                AttemptRecord(
                    request_id=request.request_id,
                    sequence=sequence,
                    purpose="inference",
                    outcome=result.status,
                    repair=repair,
                    receipt=response.receipt,
                    submitted=True,
                    http_status=response.status,
                    provider_request_id=result.provider_request_id,
                    stop_reason={
                        "completed": "stop",
                        "tool_actions": "tools",
                        "refused": "refusal",
                        "truncated": "length",
                        "failed": "error",
                    }[result.status],
                    usage=result.usage,
                    failure=result.failure.code if result.failure else None,
                )
            )
            if self.budget.remaining_seconds <= 0:
                return self._failure(
                    request, FailureCode.BUDGET_EXHAUSTED, start, result.provider_request_id
                )
            return result.model_copy(update={"usage": self.budget.usage_since(start)})
        raise BudgetExhausted()
