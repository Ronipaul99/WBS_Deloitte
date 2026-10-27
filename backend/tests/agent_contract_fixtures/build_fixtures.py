"""Rebuild synthetic fixtures/schemas only. Never loads application settings."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from app.services.agents.contracts import (
    CoverageReport,
    EvidenceReference,
    Fact,
    FactBatch,
    Requirement,
    SummaryContent,
    TenderCategory,
    TenderSummary,
    VerificationContent,
    VerificationReport,
    WorkflowInput,
)
from app.services.llm.contracts import (
    GenerationRequest,
    GenerationResult,
    ModelProfileSnapshot,
    ProviderCapabilities,
    ToolAction,
)

ROOT = Path(__file__).parent
CONTRACTS = (
    WorkflowInput,
    ModelProfileSnapshot,
    ProviderCapabilities,
    GenerationRequest,
    GenerationResult,
    ToolAction,
    EvidenceReference,
    Fact,
    Requirement,
    TenderSummary,
    CoverageReport,
    VerificationReport,
    SummaryContent,
    FactBatch,
    VerificationContent,
)
SYNTHETIC_CHUNK = "Synthetic tender 🌞\nIssuer: Example Energy Board.\nCapacity: 8 MW."


def identity(index: int) -> str:
    return str(UUID(int=index))


def fixtures() -> tuple[dict, dict]:
    scope = dict(
        zip(
            ("tenant_id", "project_id", "document_id", "processing_run_id"),
            (identity(index) for index in range(1, 5)),
            strict=True,
        ),
        source_sha256="a" * 64,
    )
    profiles = {}
    for provider, protocol in (
        ("openai", "responses"),
        ("anthropic", "anthropic_messages"),
        ("openai_compatible", "chat_completions"),
    ):
        profiles[provider] = {
            "tenant_id": identity(1),
            "connection_id": identity(5),
            "profile_id": identity(6),
            "profile_version": 1,
            "provider": provider,
            "protocol": protocol,
            "model_id": "synthetic-model-not-a-live-model",
            "enabled": False,
            "capabilities": {
                "qualification": "synthetic_fixture",
                "qualification_id": identity(7),
                "tested_at": "2026-10-27T00:00:00Z",
                "context_tokens": 8192,
                "output_tokens": 2048,
                "json_schema": "supported",
                "temperature": "supported",
            },
        }
    workflow = {
        "workflow_run_id": identity(8),
        "scope": scope,
        "processing_state": "completed",
        "requested_by": identity(9),
        "profile": profiles["openai_compatible"],
        "workflow_version": "summary-v1",
        "prompt_version": "tender-v1",
        "output_schema_version": "tender_summary.v1",
    }
    quote = "Issuer: Example Energy Board."
    summary = {
        "revision_id": identity(10),
        "workflow": workflow,
        "generated_at": "2026-10-27T00:00:00Z",
        "executive_overview": "Synthetic example; details require human review.",
        "sections": [
            {
                "category": category.value,
                "status": "unknown",
                "text": "Not established.",
            }
            for category in TenderCategory
        ],
        "facts": [
            {
                "fact_id": identity(11),
                "category": "issuer_parties",
                "critical_class": "issuer",
                "status": "supported",
                "statement": quote,
                "original_value": "Example Energy Board",
                "evidence_ids": [identity(13)],
            }
        ],
        "requirements": [
            {
                "requirement_id": identity(12),
                "display_code": "REQ-001",
                "status": "unknown",
                "obligation": "Submission requirements have not been established.",
            }
        ],
        "evidence": [
            {
                "evidence_id": identity(13),
                "scope": scope,
                "chunk_id": identity(14),
                "chunk_sha256": sha256(SYNTHETIC_CHUNK.encode()).hexdigest(),
                "physical_pages": [1],
                "heading_path": ["Synthetic tender"],
                "exact_quote": quote,
                "char_start": SYNTHETIC_CHUNK.index(quote),
                "char_end": SYNTHETIC_CHUNK.index(quote) + len(quote),
            }
        ],
        "coverage": {
            "primary_chunk_ids": [identity(14)],
            "processed_chunk_ids": [identity(14)],
            "sections": [{"section_id": "synthetic-section", "status": "processed"}],
            "unresolved_categories": [
                item.value for item in TenderCategory if item != TenderCategory.ISSUER_PARTIES
            ],
        },
        "verification": {
            "revision_id": identity(10),
            "checked_claim_ids": [identity(11), identity(12)],
            "verdict": "review_required",
        },
    }
    summary["sections"][1].update(
        status="supported",
        text=quote,
        fact_ids=[identity(11)],
    )
    summary = TenderSummary.model_validate(summary).model_dump(mode="json")
    requests = {
        provider: GenerationRequest.model_validate(
            {
                "request_id": identity(15),
                "profile": profile,
                "messages": [
                    {"role": "user", "content": "Return only the synthetic tender fixture."}
                ],
                "response_schema": "summary_content.v1",
                "input_token_budget": 2048,
                "max_output_tokens": 2048,
            }
        ).model_dump(mode="json")
        for provider, profile in profiles.items()
    }
    return summary, requests


if __name__ == "__main__":
    summary, requests = fixtures()
    for name, payload in (
        ("summary.json", summary),
        ("provider-requests.json", requests),
        ("schemas.json", {model.__name__: model.model_json_schema() for model in CONTRACTS}),
    ):
        (ROOT / name).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
