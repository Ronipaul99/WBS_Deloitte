"""Validated storage payloads; no generic graph state or prompt transcript storage."""

import json
import re
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.services.agents.contracts import FactBatch, SummaryContent, VerificationContent
from app.services.llm.contracts import Contract, Identity, Label, Positive

FORBIDDEN_KEYS = frozenset(
    {
        "apikey",
        "secret",
        "password",
        "authorization",
        "headers",
        "credentials",
        "credential",
        "accesstoken",
        "refreshtoken",
        "messages",
        "prompt",
        "prompts",
        "transcript",
        "rawresponse",
        "rawrequest",
        "chainofthought",
        "reasoning",
    }
)


def safe_json(value: dict, maximum_bytes: int = 1_048_576) -> dict:
    """Structural secret exclusion and finite JSON, not a free-text secret detector."""
    if not isinstance(value, dict):
        raise ValueError("storage payload must be a JSON object")

    def visit(item, depth=0):
        if depth > 16:
            raise ValueError("storage payload nesting exceeds limit")
        if isinstance(item, dict):
            for key, child in item.items():
                if (
                    not isinstance(key, str)
                    or re.sub(r"[^a-z0-9]", "", key.lower()) in FORBIDDEN_KEYS
                ):
                    raise ValueError("storage payload contains a forbidden field")
                visit(child, depth + 1)
        elif isinstance(item, list | tuple):
            if len(item) > 100_000:
                raise ValueError("storage array exceeds limit")
            for child in item:
                visit(child, depth + 1)

    visit(value)
    try:
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False)
    except (TypeError, ValueError, RecursionError):
        raise ValueError("storage payload must contain finite JSON data") from None
    if len(encoded.encode("utf-8")) > maximum_bytes:
        raise ValueError("storage payload exceeds byte limit")
    return json.loads(encoded)


class EndpointPolicyRecord(Contract):
    """Policy metadata only; endpoint security/approval enforcement belongs to Step 3."""

    host: Label
    port: Annotated[int, Field(strict=True, ge=1, le=65535)] = 443
    scheme: Literal["https"] = "https"
    path_prefix: Annotated[str, Field(strict=True, min_length=1, max_length=500, pattern=r"^/")]
    approval_id: Identity | None = None


class RunBudget(Contract):
    max_calls: Annotated[int, Field(strict=True, ge=1, le=120)]
    max_total_tokens: Positive
    timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=600)]


class StoredArtifact(Contract):
    kind: Literal["facts.v1", "summary_content.v1", "verification.v1"]
    payload: FactBatch | SummaryContent | VerificationContent

    @model_validator(mode="after")
    def correct_kind(self):
        expected = {
            "facts.v1": FactBatch,
            "summary_content.v1": SummaryContent,
            "verification.v1": VerificationContent,
        }[self.kind]
        if not isinstance(self.payload, expected):
            raise ValueError("artifact schema does not match its kind")
        return self
