"""Management inputs cannot assert capabilities or supply network permissions."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.services.agents.persistence_types import EndpointPolicyRecord
from app.services.llm.adapter_types import AdapterOptions, AttemptPolicy
from app.services.llm.capabilities import ProbePlan
from app.services.llm.contracts import (
    Contract,
    Identity,
    Label,
    Positive,
    Provider,
    ProviderCapabilities,
)
from app.services.llm.credentials import CredentialChange


class ConnectionCreate(Contract):
    name: Label
    provider: Provider
    approval_id: Identity
    enabled: bool = False
    credential: CredentialChange = Field(default_factory=CredentialChange, exclude=True, repr=False)


class ConnectionUpdate(Contract):
    expected_revision: Positive
    name: Label | None = None
    approval_id: Identity | None = None
    enabled: bool | None = None
    credential: CredentialChange = Field(default_factory=CredentialChange, exclude=True, repr=False)


class CredentialUpdate(Contract):
    expected_revision: Positive
    change: CredentialChange = Field(exclude=True, repr=False)


class ProfileSettings(Contract):
    context_tokens: Annotated[int, Field(strict=True, ge=512, le=1000000)] = 8192
    output_tokens: Annotated[int, Field(strict=True, ge=8, le=8192)] = 512
    temperature: Annotated[float, Field(ge=0, le=1)] | None = None
    output_mode: Literal["validated_json", "native_json_schema"] = "validated_json"
    tool_mode: Literal["none", "native", "json_actions"] = "none"
    concurrency: Literal[1] = 1
    timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=600)] = 60
    max_calls: Annotated[int, Field(strict=True, ge=1, le=120)] = 20
    max_total_tokens: Annotated[int, Field(strict=True, ge=512, le=1000000)] = 100000
    max_cost_usd: Annotated[Decimal, Field(ge=0, le=100)] | None = None
    options: AdapterOptions = Field(default_factory=AdapterOptions)
    retry: AttemptPolicy = Field(default_factory=AttemptPolicy)
    allowed_workflows: tuple[Literal["summary"], ...] = ("summary",)

    @model_validator(mode="after")
    def bounds(self):
        if self.output_tokens >= self.context_tokens or self.allowed_workflows != ("summary",):
            raise ValueError("invalid profile limits")
        return self


class ProfileCreate(Contract):
    name: Label
    connection_id: Identity
    model_id: Label
    settings: ProfileSettings = Field(default_factory=ProfileSettings)


class ProfileUpdate(Contract):
    expected_revision: Positive
    name: Label
    model_id: Label
    settings: ProfileSettings


class ProfileState(Contract):
    expected_revision: Positive
    enabled: bool
    is_default: bool = False

    @model_validator(mode="after")
    def default_enabled(self):
        if self.is_default and not self.enabled:
            raise ValueError("default must be enabled")
        return self


class TestSubmit(Contract):
    profile_id: Identity
    expected_profile_revision: Positive
    expected_connection_revision: Positive
    acknowledge_cost: Literal[True]
    operation: Literal["probe", "discovery"] = "probe"
    plan: ProbePlan = Field(default_factory=ProbePlan)


class ConnectionPublic(Contract):
    id: Identity
    name: Label
    provider: Provider
    protocol: str
    revision: Positive
    enabled: bool
    configured: bool
    endpoint: EndpointPolicyRecord


class ProfilePublic(Contract):
    id: Identity
    name: Label
    connection_id: Identity
    revision: Positive
    version: Positive
    model_id: Label
    provider: Provider
    enabled: bool
    is_default: bool
    usable: bool
    availability: Literal["usable", "disabled", "unverified", "stale"]
    qualification: str
    tested_at: datetime | None
    settings: dict
    capabilities: ProviderCapabilities
    candidate_fingerprint: str | None = None


class TestPublic(Contract):
    id: Identity
    connection_id: Identity
    profile_id: Identity
    state: Literal["queued", "running", "succeeded", "failed", "unavailable"]
    error_code: str | None
    result: dict
    calls_reserved: int
    tokens_reserved: int
