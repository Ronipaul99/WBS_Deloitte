"""Only validated non-secret configuration and receipts enter durable test storage."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.schemas.llm import ProfileSettings
from app.services.agents.persistence_types import EndpointPolicyRecord
from app.services.llm.adapter_types import AttemptRecord
from app.services.llm.capabilities import LiveProbePermit, ProbePlan
from app.services.llm.contracts import Contract, ModelProfileSnapshot, Sha256


class TestConfiguration(Contract):
    operation: Literal["probe", "discovery"]
    profile: ModelProfileSnapshot
    settings: ProfileSettings
    endpoint: EndpointPolicyRecord
    connection_revision: int = Field(ge=1)
    profile_revision: int = Field(ge=1)
    fingerprint: Sha256
    plan: ProbePlan
    permit: LiveProbePermit


class TestLedger(Contract):
    deadline: datetime
    calls: Annotated[int, Field(strict=True, ge=0, le=9)] = 0
    reserved_tokens: Annotated[int, Field(strict=True, ge=0, le=1000000)] = 0
    records: Annotated[tuple[AttemptRecord, ...], Field(max_length=9)] = ()
    violated: bool = False

    @model_validator(mode="after")
    def valid(self):
        if self.deadline.utcoffset() is None:
            raise ValueError("aware deadline required")
        seq = [r.sequence for r in self.records]
        if len(seq) != len(set(seq)) or any(s > self.calls for s in seq):
            raise ValueError("invalid test ledger")
        return self


class ManagementError(Exception):
    def __init__(self, code="llm_unavailable", status=503):
        self.code, self.status = code, status
        super().__init__(code)
