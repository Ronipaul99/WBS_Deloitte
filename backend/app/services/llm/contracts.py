"""Versioned, secret-free inference boundary. This module performs no I/O.

Credentials/endpoints are deliberately absent. Only trusted application code may
create profile snapshots. Validation does not replace authorization or egress checks.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def _non_nil(value: UUID) -> UUID:
    if value.int == 0:
        raise ValueError("nil identity is invalid")
    return value


Identity = Annotated[UUID, AfterValidator(_non_nil)]
Label = Annotated[str, Field(strict=True, min_length=1, max_length=160, pattern=r"\S")]
Text = Annotated[str, Field(strict=True, min_length=1, max_length=8000, pattern=r"\S")]
Version = Annotated[
    str, Field(strict=True, min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
]
Sha256 = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
Count = Annotated[int, Field(strict=True, ge=0, le=10_000_000)]
Positive = Annotated[int, Field(strict=True, ge=1, le=1_000_000)]
Flag = Annotated[bool, Field(strict=True)]


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        validate_default=True,
        revalidate_instances="always",
        allow_inf_nan=False,
    )
    schema_version: Literal["1.0"] = "1.0"


def unique(values: Sequence[object]) -> None:
    if len(values) != len(set(values)):
        raise ValueError("duplicate identities are invalid")


class Provider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    COMPATIBLE = "openai_compatible"


class APIProtocol(StrEnum):
    RESPONSES = "responses"
    MESSAGES = "anthropic_messages"
    CHAT_COMPLETIONS = "chat_completions"


class Support(StrEnum):
    UNKNOWN = "unknown"
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class ProviderCapabilities(Contract):
    qualification: Literal["pending", "synthetic_fixture", "live_worker"] = "pending"
    qualification_id: Identity | None = None
    tested_at: datetime | None = None
    context_tokens: Positive | None = None
    output_tokens: Positive | None = None
    native_tools: Support = Support.UNKNOWN
    json_schema: Support = Support.UNKNOWN
    temperature: Support = Support.UNKNOWN
    usage: Support = Support.UNKNOWN
    refusal: Support = Support.UNKNOWN
    truncation: Support = Support.UNKNOWN

    @model_validator(mode="after")
    def consistent_observations(self) -> ProviderCapabilities:
        observations = (
            self.native_tools,
            self.json_schema,
            self.temperature,
            self.usage,
            self.refusal,
            self.truncation,
        )
        if self.qualification == "pending":
            if any(item != Support.UNKNOWN for item in observations) or any(
                item is not None
                for item in (
                    self.qualification_id,
                    self.tested_at,
                    self.context_tokens,
                    self.output_tokens,
                )
            ):
                raise ValueError("pending capabilities cannot advertise observations")
        elif (
            self.qualification_id is None
            or self.tested_at is None
            or self.tested_at.utcoffset() is None
        ):
            raise ValueError("observations require an identity and timezone-aware timestamp")
        if (
            self.context_tokens is not None
            and self.output_tokens is not None
            and self.output_tokens >= self.context_tokens
        ):
            raise ValueError("output limit must leave input context")
        return self


class ModelProfileSnapshot(Contract):
    tenant_id: Identity
    connection_id: Identity
    profile_id: Identity
    profile_version: Positive
    provider: Provider
    protocol: APIProtocol
    model_id: Label
    capabilities: ProviderCapabilities
    enabled: Flag = False
    timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=600)] = 60
    max_calls: Annotated[int, Field(strict=True, ge=1, le=120)] = 120
    max_total_tokens: Positive = 100_000

    @model_validator(mode="after")
    def qualified_protocol(self) -> ModelProfileSnapshot:
        pairs = {
            Provider.OPENAI: APIProtocol.RESPONSES,
            Provider.ANTHROPIC: APIProtocol.MESSAGES,
            Provider.COMPATIBLE: APIProtocol.CHAT_COMPLETIONS,
        }
        if pairs[self.provider] != self.protocol:
            raise ValueError("provider requires its registered protocol")
        caps = self.capabilities
        if self.enabled and (
            caps.qualification != "live_worker"
            or caps.context_tokens is None
            or caps.output_tokens is None
        ):
            raise ValueError("enabled profiles require live worker qualification and limits")
        return self


class FailureCode(StrEnum):
    CONFIGURATION = "configuration"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    CONTEXT_OVERFLOW = "context_overflow"
    REFUSAL = "refusal"
    TRUNCATED = "truncated"
    INVALID_SCHEMA = "invalid_schema"
    BUDGET_EXHAUSTED = "budget_exhausted"
    STALE_INPUT = "stale_input"
    DELETING_INPUT = "deleting_input"
    CANCELLED = "cancelled"
    EVIDENCE_VERIFICATION = "evidence_verification"


class SafeFailure(Contract):
    """No upstream message, body, URL, stack trace, or arbitrary metadata."""

    code: FailureCode
    correlation_id: Identity


class SearchDocument(Contract):
    name: Literal["search_document"]
    query: Annotated[str, Field(strict=True, min_length=1, max_length=1000, pattern=r"\S")]
    section_filter: Label | None = None
    limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 5


class ReadSection(Contract):
    name: Literal["read_section"]
    section_id: Label
    cursor: Annotated[int, Field(strict=True, ge=0, le=100_000)] = 0


class ReadChunkNeighbors(Contract):
    name: Literal["read_chunk_neighbors"]
    chunk_ids: Annotated[tuple[Identity, ...], Field(min_length=1, max_length=10)]
    radius: Annotated[int, Field(strict=True, ge=0, le=2)] = 1

    @model_validator(mode="after")
    def distinct_chunks(self) -> ReadChunkNeighbors:
        unique(self.chunk_ids)
        return self


class LookupDefinition(Contract):
    name: Literal["lookup_definition"]
    term: Label


class ToolAction(Contract):
    """Model-selected arguments only. Trusted code injects authorized run scope."""

    call_id: Label
    arguments: Annotated[
        SearchDocument | ReadSection | ReadChunkNeighbors | LookupDefinition,
        Field(discriminator="name"),
    ]


class Message(Contract):
    role: Literal["system", "user", "assistant"]
    content: Text


class ToolExchange(Contract):
    """A completed, trusted tool exchange for protocol replay; never executes a tool."""

    action: ToolAction
    output_json: Annotated[str, Field(strict=True, min_length=2, max_length=64_000)]
    is_error: Flag = False

    @model_validator(mode="after")
    def json_object(self):
        value = json.loads(
            self.output_json,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
        if not isinstance(value, dict):
            raise ValueError("tool output must be a JSON object")
        return self


class GenerationRequest(Contract):
    request_id: Identity
    profile: ModelProfileSnapshot
    messages: Annotated[tuple[Message, ...], Field(min_length=1, max_length=32)]
    response_schema: Literal[
        "facts.v1", "analyst.v1", "writer_fragment.v1", "summary_content.v1", "verification.v1"
    ]
    output_mode: Literal["validated_json", "native_json_schema"] = "validated_json"
    allowed_tools: Annotated[
        tuple[
            Literal["search_document", "read_section", "read_chunk_neighbors", "lookup_definition"],
            ...,
        ],
        Field(max_length=4),
    ] = ()
    input_token_budget: Positive
    max_output_tokens: Positive
    temperature: Annotated[float, Field(strict=True, ge=0, le=2)] | None = None
    tool_results: Annotated[tuple[ToolExchange, ...], Field(max_length=4)] = ()

    @model_validator(mode="after")
    def within_profile(self) -> GenerationRequest:
        caps = self.profile.capabilities
        unique(self.allowed_tools)
        unique(tuple(item.action.call_id for item in self.tool_results))
        if any(item.action.arguments.name not in self.allowed_tools for item in self.tool_results):
            raise ValueError("tool replay is outside the request allowlist")
        if caps.context_tokens is None or caps.output_tokens is None:
            raise ValueError("request requires qualified token limits")
        if (
            self.input_token_budget + self.max_output_tokens > caps.context_tokens
            or self.max_output_tokens > caps.output_tokens
            or self.input_token_budget + self.max_output_tokens > self.profile.max_total_tokens
        ):
            raise ValueError("request exceeds context/output/run budget")
        if self.output_mode == "native_json_schema" and caps.json_schema != Support.SUPPORTED:
            raise ValueError("native schema support has not been demonstrated")
        if self.temperature is not None and caps.temperature != Support.SUPPORTED:
            raise ValueError("temperature support has not been demonstrated")
        return self


class Usage(Contract):
    source: Literal["reported", "estimated", "unknown"] = "unknown"
    input_tokens: Count | None = None
    output_tokens: Count | None = None

    @model_validator(mode="after")
    def honest_counts(self) -> Usage:
        if self.source == "unknown":
            if self.input_tokens is not None or self.output_tokens is not None:
                raise ValueError("unknown usage must not report counts")
        elif self.input_tokens is None or self.output_tokens is None:
            raise ValueError("known usage requires both counts")
        return self


class GenerationResult(Contract):
    request_id: Identity
    status: Literal["completed", "tool_actions", "refused", "truncated", "failed"]
    # Bounded JSON text is untrusted until parsed into the requested output contract.
    output_json: Annotated[str, Field(strict=True, min_length=2, max_length=500_000)] | None = None
    actions: Annotated[tuple[ToolAction, ...], Field(max_length=4)] = ()
    failure: SafeFailure | None = None
    usage: Usage = Field(default_factory=Usage)
    provider_request_id: (
        Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")] | None
    ) = None

    @model_validator(mode="after")
    def exclusive_outcome(self) -> GenerationResult:
        if self.status == "completed":
            if self.output_json is None or self.actions or self.failure is not None:
                raise ValueError("completed result requires only output JSON")
            try:
                payload = json.loads(
                    self.output_json,
                    parse_constant=_reject_constant,
                    object_pairs_hook=_unique_object,
                )
            except (ValueError, RecursionError) as error:
                raise ValueError("completed result requires a valid JSON object") from error
            if not isinstance(payload, dict):
                raise ValueError("completed result requires a JSON object")
        elif self.status == "tool_actions":
            if not self.actions or self.output_json is not None or self.failure is not None:
                raise ValueError("tool result requires only actions")
            unique(tuple(action.call_id for action in self.actions))
        else:
            if self.output_json is not None or self.actions or self.failure is None:
                raise ValueError("incomplete results must contain only a safe failure")
            required = {"refused": FailureCode.REFUSAL, "truncated": FailureCode.TRUNCATED}
            if self.status in required and self.failure.code != required[self.status]:
                raise ValueError("failure code does not match outcome")
        return self


def _reject_constant(value: str):
    raise ValueError("non-finite JSON constant")


def _finite_float(value: str):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite JSON number")
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def validate_result_binding(request: GenerationRequest, result: GenerationResult) -> None:
    """Contract-only correlation/allowlist check; does not execute tools or parse a draft."""
    if request.request_id != result.request_id:
        raise ValueError("result belongs to another request")
    if any(action.arguments.name not in request.allowed_tools for action in result.actions):
        raise ValueError("result requests a tool outside the request allowlist")


class GenerationProvider(Protocol):
    """Adapters normalize responses; callers validate JSON and allowed tool actions.

    No implementation, network access, retry loop, or credential lookup in Step 1.
    """

    async def generate(self, request: GenerationRequest) -> GenerationResult: ...
