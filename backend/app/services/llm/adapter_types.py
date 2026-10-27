"""Secret-free adapter metadata and caller-owned, in-process admission budgets."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.services.llm.contracts import (
    Contract,
    FailureCode,
    Identity,
    ModelProfileSnapshot,
    Positive,
    Sha256,
    Usage,
)
from app.services.llm.credentials import CredentialReceipt
from app.services.llm.endpoint_policy import PinnedEndpoint


def fingerprint(
    profile: ModelProfileSnapshot,
    pinned: PinnedEndpoint,
    options: Contract,
    *,
    include_capabilities=True,
) -> str:
    excluded = {"enabled"} if include_capabilities else {"enabled", "capabilities"}
    value = {
        "profile": profile.model_dump(mode="json", exclude=excluded),
        "approval": pinned.approval.model_dump(mode="json"),
        "options": options.model_dump(mode="json"),
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class AdapterOptions(Contract):
    compatible_token_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"


class QualificationBinding(Contract):
    """Trusted reference to existing qualification, not a qualification generator."""

    qualification_id: Identity
    origin: Literal["synthetic_fixture", "live_worker"]
    tested_at: datetime
    fingerprint: Sha256

    @model_validator(mode="after")
    def aware(self):
        if self.tested_at.utcoffset() is None:
            raise ValueError("qualification requires aware time")
        return self

    def matches(self, profile, pinned, options):
        caps = profile.capabilities
        return (
            self.qualification_id == caps.qualification_id
            and self.origin == caps.qualification
            and self.tested_at == caps.tested_at
            and self.fingerprint == fingerprint(profile, pinned, options)
        )


class AttemptPolicy(Contract):
    max_attempts: Annotated[int, Field(strict=True, ge=1, le=8)] = 3
    allow_format_repair: bool = True
    retry_statuses: Annotated[tuple[int, ...], Field(max_length=4)] = (429,)
    retry_before_submit: bool = True
    retry_ambiguous_submission: bool = False
    base_delay_seconds: Annotated[float, Field(ge=0, le=5)] = 0.25
    max_delay_seconds: Annotated[float, Field(ge=0, le=30)] = 5.0

    @model_validator(mode="after")
    def supported_retries(self):
        if len(set(self.retry_statuses)) != len(self.retry_statuses) or any(
            type(value) is not int or value not in {429, 502, 503, 504}
            for value in self.retry_statuses
        ):
            raise ValueError("unsupported retry status")
        if self.base_delay_seconds > self.max_delay_seconds:
            raise ValueError("backoff exceeds delay bound")
        return self


class AttemptRecord(Contract):
    request_id: Identity
    sequence: Positive
    purpose: Literal["inference", "test", "discovery"]
    outcome: Literal["completed", "tool_actions", "refused", "truncated", "failed", "invalid"]
    repair: bool = False
    receipt: CredentialReceipt | None = None
    submitted: bool = False
    http_status: Annotated[int, Field(strict=True, ge=100, le=599)] | None = None
    provider_request_id: (
        Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")] | None
    ) = None
    stop_reason: Literal["stop", "tools", "refusal", "length", "error"]
    usage: Usage = Field(default_factory=Usage)
    failure: FailureCode | None = None


class BudgetExhausted(Exception):
    def __init__(self):
        super().__init__("adapter budget exhausted")


class CallBudget:
    """Share one instance across retries/repairs/probes/tasks in a run. No persistence.

    Reservations charge the requested input+output ceilings and are not refunded,
    including after unknown usage. They are admission allowances, not billing counts.
    """

    def __init__(self, *, max_calls: int, max_tokens: int, total_seconds: float, clock=None):
        if (
            type(max_calls) is not int
            or not 1 <= max_calls <= 120
            or type(max_tokens) is not int
            or not 1 <= max_tokens <= 1_000_000
            or type(total_seconds) not in (int, float)
            or not 0 < total_seconds <= 3600
        ):
            raise ValueError("invalid adapter budget")
        self.max_calls = max_calls
        self.max_tokens = max_tokens
        self._clock = clock or time.monotonic
        self._deadline = self._clock() + total_seconds
        self.calls = 0
        self.reserved_tokens = 0
        self._records = []
        self._repairs = set()
        self.lock = asyncio.Lock()
        self._binding = None
        self._violated = False

    def bind(self, identity):
        if self._binding is not None and self._binding != identity:
            raise ValueError("budget cannot switch provider/profile/endpoint")
        self._binding = identity

    def validate_provider(self, profile, pinned, options):
        """Optional trusted workflow pin check; in-process callers retain prior behavior."""

    @property
    def remaining_seconds(self):
        return max(0.0, self._deadline - self._clock())

    @property
    def records(self) -> tuple[AttemptRecord, ...]:
        return tuple(self._records)

    def reserve(self, input_ceiling, output_ceiling):
        tokens = input_ceiling + output_ceiling
        if (
            self._violated
            or self.calls >= self.max_calls
            or self.reserved_tokens + tokens > self.max_tokens
            or self.remaining_seconds <= 0
        ):
            raise BudgetExhausted()
        self.calls += 1
        self.reserved_tokens += tokens
        return self.calls

    def observe_overrun(self, extra_tokens):
        self.reserved_tokens += max(0, extra_tokens)
        self._violated = True  # A server ignoring ceilings must not receive another attempt.

    def begin_repair(self, request_id):
        if self._repairs:
            raise BudgetExhausted()
        self._repairs.add(request_id)

    def record(self, item: AttemptRecord):
        if len(self._records) >= self.max_calls:
            raise BudgetExhausted()
        self._records.append(item)

    async def before_attempt(self, input_ceiling, output_ceiling):
        return self.reserve(input_ceiling, output_ceiling)

    async def before_repair(self, request_id):
        self.begin_repair(request_id)

    async def after_attempt(self, item):
        self.record(item)

    async def after_overrun(self, extra_tokens):
        self.observe_overrun(extra_tokens)

    def usage_since(self, start):
        records = self._records[start:]
        if not records or any(item.usage.source != "reported" for item in records):
            return Usage()
        inputs, outputs = (
            sum(i.usage.input_tokens for i in records),
            sum(i.usage.output_tokens for i in records),
        )
        if max(inputs, outputs) > 10_000_000:
            return Usage()
        return Usage(source="reported", input_tokens=inputs, output_tokens=outputs)
