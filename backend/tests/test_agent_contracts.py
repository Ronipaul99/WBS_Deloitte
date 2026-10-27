"""Pure Step 1 tests. Run --noconftest to preserve existing upload fixtures."""

from __future__ import annotations

import asyncio
import copy
import json
from hashlib import sha256
from pathlib import Path

import pytest
from agent_contract_fixtures.build_fixtures import CONTRACTS, SYNTHETIC_CHUNK, fixtures, identity
from pydantic import ValidationError

from app.services.agents.contracts import (
    OUTPUT_CONTRACTS,
    CoverageReport,
    EvidenceReference,
    Fact,
    Requirement,
    SummaryContent,
    TenderSummary,
    Transition,
    VerificationReport,
    WorkflowInput,
)
from app.services.llm.contracts import (
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ModelProfileSnapshot,
    ProviderCapabilities,
    SafeFailure,
    ToolAction,
    Usage,
    validate_result_binding,
)

ROOT = Path(__file__).parent / "agent_contract_fixtures"


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


@pytest.fixture
def summary():
    return load("summary.json")


@pytest.fixture
def generation_request():
    return load("provider-requests.json")["openai_compatible"]


def test_synthetic_fixture_generation_and_schema_snapshots():
    summary, requests = fixtures()
    assert summary == load("summary.json")
    assert requests == load("provider-requests.json")
    assert {model.__name__: model.model_json_schema() for model in CONTRACTS} == load(
        "schemas.json"
    )


def test_summary_roundtrip_and_immutable_nested_scope(summary):
    parsed = TenderSummary.model_validate(summary)
    assert parsed == TenderSummary.model_validate_json(parsed.model_dump_json())
    assert parsed.coverage.complete is True
    assert parsed.review_state == "draft"
    assert isinstance(parsed.facts, tuple)
    with pytest.raises(ValidationError):
        parsed.workflow.scope.tenant_id = identity(99)


@pytest.mark.parametrize(
    "field",
    [
        "workflow_run_id",
        "scope",
        "processing_state",
        "requested_by",
        "profile",
        "workflow_version",
        "prompt_version",
        "output_schema_version",
    ],
)
def test_required_workflow_fields(summary, field):
    payload = summary["workflow"]
    del payload[field]
    with pytest.raises(ValidationError):
        WorkflowInput.model_validate(payload)


@pytest.mark.parametrize(
    "field", ["tenant_id", "project_id", "document_id", "processing_run_id", "source_sha256"]
)
def test_required_pinned_scope(summary, field):
    del summary["workflow"]["scope"][field]
    with pytest.raises(ValidationError):
        WorkflowInput.model_validate(summary["workflow"])


@pytest.mark.parametrize("value", ["pending", "failed", "cancelled"])
def test_only_completed_source_assertion(summary, value):
    summary["workflow"]["processing_state"] = value
    with pytest.raises(ValidationError):
        WorkflowInput.model_validate(summary["workflow"])


@pytest.mark.parametrize("value", ["", "version with spaces", "v" * 81])
def test_version_bounds(summary, value):
    summary["workflow"]["workflow_version"] = value
    with pytest.raises(ValidationError):
        WorkflowInput.model_validate(summary["workflow"])


def test_profile_scope_must_match_workflow(summary):
    summary["workflow"]["profile"]["tenant_id"] = identity(99)
    with pytest.raises(ValidationError):
        WorkflowInput.model_validate(summary["workflow"])


@pytest.mark.parametrize(
    "key", ["api_key", "credential", "authorization", "base_url", "headers", "password", "metadata"]
)
@pytest.mark.parametrize("target", ["workflow", "scope", "profile", "capabilities"])
def test_secret_transport_fields_forbidden(summary, key, target):
    workflow = summary["workflow"]
    node = {
        "workflow": workflow,
        "scope": workflow["scope"],
        "profile": workflow["profile"],
        "capabilities": workflow["profile"]["capabilities"],
    }[target]
    node[key] = "SYNTHETIC_SECRET_SENTINEL"
    with pytest.raises(ValidationError) as error:
        WorkflowInput.model_validate(workflow)
    # Human-readable exceptions suppress input; callers must also suppress structured inputs.
    assert "SYNTHETIC_SECRET_SENTINEL" not in str(error.value)
    assert "SYNTHETIC_SECRET_SENTINEL" not in json.dumps(error.value.errors(include_input=False))


def test_no_secret_fields_in_workflow_schema(summary):
    schema = WorkflowInput.model_json_schema()
    for definition in (schema, *schema["$defs"].values()):
        assert not {"api_key", "headers", "credential", "base_url", "password"} & set(
            definition.get("properties", {})
        )
        if definition.get("type") == "object":
            assert definition["additionalProperties"] is False
    assert (
        "SYNTHETIC_SECRET_SENTINEL"
        not in WorkflowInput.model_validate(summary["workflow"]).model_dump_json()
    )


@pytest.mark.parametrize(
    "change",
    [
        {"provider": "custom_rest"},
        {"protocol": "responses"},
        {"profile_version": True},
        {"profile_version": 0},
        {"profile_version": "1"},
        {"model_id": "x" * 161},
        {"profile_id": "00000000-0000-0000-0000-000000000000"},
        {"enabled": True},
        {"max_calls": 121},
    ],
)
def test_invalid_profile(generation_request, change):
    with pytest.raises(ValidationError):
        ModelProfileSnapshot.model_validate({**generation_request["profile"], **change})


@pytest.mark.parametrize(
    "change",
    [
        {"native_tools": "supported"},
        {"context_tokens": 8192},
        {"tested_at": "2026-10-27T00:00:00Z"},
    ],
)
def test_pending_capabilities_cannot_claim_observations(change):
    with pytest.raises(ValidationError):
        ProviderCapabilities.model_validate(change)


def test_observed_capabilities_need_qualification_evidence(generation_request):
    caps = generation_request["profile"]["capabilities"]
    caps["tested_at"] = "2026-10-27T00:00:00"
    with pytest.raises(ValidationError):
        ProviderCapabilities.model_validate(caps)
    caps["tested_at"] = "2026-10-27T00:00:00Z"
    caps["context_tokens"] = caps["output_tokens"]
    with pytest.raises(ValidationError):
        ProviderCapabilities.model_validate(caps)


@pytest.mark.parametrize(
    "change",
    [
        {"max_output_tokens": 2049},
        {"input_token_budget": 8192},
        {"temperature": float("nan")},
        {"max_output_tokens": True},
        {"messages": []},
        {"messages": [{"role": "tool", "content": "x"}]},
        {"allowed_tools": ["shell"]},
        {"allowed_tools": ["search_document", "search_document"]},
    ],
)
def test_generation_bounds(generation_request, change):
    with pytest.raises(ValidationError):
        GenerationRequest.model_validate({**generation_request, **change})


@pytest.mark.parametrize(
    "capability,change",
    [
        ("json_schema", {"output_mode": "native_json_schema"}),
        ("temperature", {"temperature": 0.5}),
    ],
)
def test_request_does_not_assume_native_settings(generation_request, capability, change):
    generation_request["profile"]["capabilities"][capability] = "unknown"
    with pytest.raises(ValidationError):
        GenerationRequest.model_validate({**generation_request, **change})


@pytest.mark.parametrize(
    "arguments",
    [
        {"name": "search_document", "query": "security requirements"},
        {"name": "read_section", "section_id": "section-1", "cursor": 2},
        {"name": "read_chunk_neighbors", "chunk_ids": [identity(14)], "radius": 2},
        {"name": "lookup_definition", "term": "PBG"},
    ],
)
def test_allowlisted_tool_actions(arguments):
    tool = ToolAction.model_validate({"call_id": "call-1", "arguments": arguments})
    assert tool.arguments.name == arguments["name"]
    assert ToolAction.model_validate_json(tool.model_dump_json()) == tool


@pytest.mark.parametrize(
    "arguments",
    [
        {"name": "http", "url": "https://example.invalid"},
        {"name": "search_document", "query": "x", "tenant_id": identity(99)},
        {"name": "read_section", "section_id": "s", "document_id": identity(99)},
        {"name": "read_chunk_neighbors", "chunk_ids": [identity(14)], "radius": 3},
        {"name": "read_chunk_neighbors", "chunk_ids": [identity(14)] * 2},
        {"name": "lookup_definition", "term": "x", "sql": "SELECT 1"},
        {"name": "search_document", "query": "x" * 1001},
        {"name": "read_section", "section_id": "s", "cursor": -1},
    ],
)
def test_tools_cannot_choose_scope_or_unbounded_actions(arguments):
    with pytest.raises(ValidationError):
        ToolAction.model_validate({"call_id": "call-1", "arguments": arguments})


def test_result_binding_and_tool_allowlist(generation_request):
    parsed = GenerationRequest.model_validate(generation_request)
    result = GenerationResult.model_validate(
        {
            "request_id": parsed.request_id,
            "status": "tool_actions",
            "actions": [
                {"call_id": "c", "arguments": {"name": "lookup_definition", "term": "EMD"}}
            ],
        }
    )
    with pytest.raises(ValueError, match="allowlist"):
        validate_result_binding(parsed, result)
    generation_request["allowed_tools"] = ["lookup_definition"]
    validate_result_binding(GenerationRequest.model_validate(generation_request), result)
    generation_request["request_id"] = identity(98)
    with pytest.raises(ValueError, match="another request"):
        validate_result_binding(GenerationRequest.model_validate(generation_request), result)


@pytest.mark.parametrize(
    "status,code",
    [("refused", "refusal"), ("truncated", "truncated"), ("failed", "provider_unavailable")],
)
def test_incomplete_results_never_carry_success_payload(status, code):
    payload = {
        "request_id": identity(15),
        "status": status,
        "failure": {"code": code, "correlation_id": identity(16)},
    }
    assert GenerationResult.model_validate(payload).output_json is None
    with pytest.raises(ValidationError):
        GenerationResult.model_validate({**payload, "output_json": "{}"})
    with pytest.raises(ValidationError):
        GenerationResult.model_validate({**payload, "failure": None})


@pytest.mark.parametrize(
    "output",
    ["broken", "{", "[]", "null", '{"x":NaN}', '{"x":1,"x":2}', "x" * 500_001],
    ids=["plain", "partial", "array", "null", "nan", "duplicate-key", "oversized"],
)
def test_completed_result_requires_bounded_valid_object(output):
    with pytest.raises(ValidationError):
        GenerationResult.model_validate(
            {"request_id": identity(15), "status": "completed", "output_json": output}
        )


def test_safe_failure_excludes_upstream_detail():
    with pytest.raises(ValidationError):
        SafeFailure.model_validate(
            {
                "code": "configuration",
                "correlation_id": identity(16),
                "raw_body": "SYNTHETIC_SECRET_SENTINEL",
            }
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"source": "reported"},
        {"source": "unknown", "input_tokens": 0},
        {"source": "estimated", "input_tokens": -1, "output_tokens": 1},
    ],
)
def test_usage_never_fabricates_counts(payload):
    with pytest.raises(ValidationError):
        Usage.model_validate(payload)


def test_unicode_evidence_contract_uses_codepoints(summary):
    item = EvidenceReference.model_validate(summary["evidence"][0])
    assert SYNTHETIC_CHUNK[item.char_start : item.char_end] == item.exact_quote
    assert sha256(SYNTHETIC_CHUNK.encode()).hexdigest() == item.chunk_sha256
    assert len(SYNTHETIC_CHUNK[: item.char_start].encode("utf-16-le")) // 2 != item.char_start


@pytest.mark.parametrize(
    "change",
    [
        {"physical_pages": [0]},
        {"physical_pages": [2, 1]},
        {"physical_pages": [1, 1]},
        {"physical_pages": [True]},
        {"char_start": -1},
        {"char_end": 1},
        {"row_id": "row-1"},
        {"chunk_sha256": "invalid"},
        {"offset_unit": "utf16"},
        {"exact_quote": "x" * 8001},
    ],
)
def test_invalid_evidence_bounds(summary, change):
    with pytest.raises(ValidationError):
        EvidenceReference.model_validate({**summary["evidence"][0], **change})


@pytest.mark.parametrize(
    "scope_field", ["tenant_id", "project_id", "document_id", "processing_run_id", "source_sha256"]
)
def test_no_cross_scope_evidence(summary, scope_field):
    summary["evidence"][0]["scope"][scope_field] = (
        "b" * 64 if scope_field == "source_sha256" else identity(99)
    )
    with pytest.raises(ValidationError):
        TenderSummary.model_validate(summary)


def test_fact_support_states_are_distinct(summary):
    fact = summary["facts"][0]
    with pytest.raises(ValidationError):
        Fact.model_validate({**fact, "evidence_ids": []})
    with pytest.raises(ValidationError):
        Fact.model_validate({**fact, "status": "unknown"})
    with pytest.raises(ValidationError):
        Fact.model_validate({**fact, "status": "conflicting", "alternatives": ["one"]})
    assert (
        Fact.model_validate(
            {**fact, "status": "conflicting", "alternatives": ["one", "two"]}
        ).status
        == "conflicting"
    )
    assert (
        Fact.model_validate({**fact, "status": "unsupported", "evidence_ids": []}).status
        == "unsupported"
    )


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1e9", 123.4, "01.0"])
def test_financial_normalization_is_exact_decimal_string(summary, value):
    with pytest.raises(ValidationError):
        Fact.model_validate({**summary["facts"][0], "normalized_number": value})


def test_supported_requirements_need_sources_and_stable_dependencies(summary):
    requirement = summary["requirements"][0]
    with pytest.raises(ValidationError):
        Requirement.model_validate({**requirement, "status": "supported"})
    with pytest.raises(ValidationError):
        Requirement.model_validate({**requirement, "dependency_ids": [identity(12)]})


@pytest.mark.parametrize(
    "change",
    [
        {"processed_chunk_ids": []},
        {"unprocessed_chunk_ids": [identity(14)]},
        {"processed_chunk_ids": [identity(99)]},
        {"primary_chunk_ids": [identity(14), identity(14)]},
    ],
)
def test_coverage_inventory_is_exact_partition(summary, change):
    with pytest.raises(ValidationError):
        CoverageReport.model_validate({**summary["coverage"], **change})


def test_partial_coverage_is_truthful_and_blocks_acceptance(summary):
    summary["coverage"].update(processed_chunk_ids=[], unprocessed_chunk_ids=[identity(14)])
    coverage = CoverageReport.model_validate(summary["coverage"])
    assert not coverage.complete
    with pytest.raises(ValidationError):
        TenderSummary.model_validate(summary)
    summary["verification"]["verdict"] = "quality_blocked"
    assert TenderSummary.model_validate(summary).verification.verdict == "quality_blocked"


@pytest.mark.parametrize(
    "change",
    [
        "missing_evidence",
        "duplicate_claim",
        "missing_claim",
        "missing_category",
        "wrong_revision",
        "unverified_claim",
        "approved",
        "unsupported_critical",
    ],
)
def test_summary_integrity(summary, change):
    if change == "missing_evidence":
        summary["evidence"] = []
    elif change == "duplicate_claim":
        summary["facts"] *= 2
    elif change == "missing_claim":
        summary["sections"][1]["fact_ids"] = [identity(99)]
    elif change == "missing_category":
        summary["sections"][0]["category"] = "issuer_parties"
    elif change == "wrong_revision":
        summary["verification"]["revision_id"] = identity(99)
    elif change == "unverified_claim":
        summary["verification"]["checked_claim_ids"] = []
    elif change == "approved":
        summary["review_state"] = "approved"
    else:
        summary["facts"][0]["status"] = "unsupported"
    with pytest.raises(ValidationError):
        TenderSummary.model_validate(summary)


def test_verifier_cannot_ignore_critical_failure(summary):
    payload = summary["verification"]
    payload["findings"] = [
        {
            "claim_id": identity(11),
            "severity": "critical",
            "code": "unsupported",
            "detail": "Synthetic unsupported claim.",
        }
    ]
    with pytest.raises(ValidationError):
        VerificationReport.model_validate(payload)
    payload["verdict"] = "quality_blocked"
    assert VerificationReport.model_validate(payload).verdict == "quality_blocked"


@pytest.mark.parametrize(
    "source,target,actor,repair_pass",
    [
        ("pinned", "reading", "controller", 0),
        ("reading", "consolidating", "analyst", 0),
        ("consolidating", "writing", "controller", 0),
        ("writing", "verifying", "writer", 0),
        ("verifying", "repairing", "verifier", 0),
        ("repairing", "verifying", "writer", 1),
        ("verifying", "human_review", "verifier", 1),
        ("human_review", "approved", "human_reviewer", 1),
        ("verifying", "quality_blocked", "verifier", 1),
        ("writing", "cancelled", "controller", 0),
    ],
)
def test_legal_transitions(source, target, actor, repair_pass):
    assert Transition(source=source, target=target, actor=actor, repair_pass=repair_pass)


@pytest.mark.parametrize(
    "source,target,actor,repair_pass",
    [
        ("verifying", "repairing", "verifier", 1),
        ("repairing", "verifying", "writer", 0),
        ("writing", "approved", "writer", 0),
        ("human_review", "approved", "verifier", 0),
        ("cancelled", "writing", "controller", 0),
        ("verifying", "human_review", "verifier", 2),
    ],
)
def test_illegal_transitions_and_second_repair(source, target, actor, repair_pass):
    with pytest.raises(ValidationError):
        Transition(source=source, target=target, actor=actor, repair_pass=repair_pass)


class FakeProvider:
    """Canonical fixture transport only; this does not qualify any real protocol."""

    def __init__(self, content):
        self.content = content

    async def generate(self, generation_request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            request_id=generation_request.request_id,
            status="completed",
            output_json=json.dumps(self.content),
        )


def test_three_provider_fixtures_produce_equivalent_normalized_writer_content(summary):
    content = {
        key: copy.deepcopy(summary[key]) for key in ("executive_overview", "sections", "key_points")
    }
    provider: GenerationProvider = FakeProvider(content)
    outputs = []
    for fixture in load("provider-requests.json").values():
        generation_request = GenerationRequest.model_validate(fixture)
        result = asyncio.run(provider.generate(generation_request))
        validate_result_binding(generation_request, result)
        outputs.append(SummaryContent.model_validate_json(result.output_json))
    assert outputs[0] == outputs[1] == outputs[2]
    with pytest.raises(ValidationError):
        SummaryContent.model_validate({**content, "tenant_id": identity(99)})
    with pytest.raises(ValidationError):
        SummaryContent.model_validate({**content, "workflow": summary["workflow"]})


def test_valid_json_is_not_necessarily_valid_output_schema(generation_request):
    result = GenerationResult(request_id=identity(15), status="completed", output_json='{"x":1}')
    with pytest.raises(ValidationError):
        SummaryContent.model_validate_json(result.output_json)


@pytest.mark.parametrize("schema_id", ["facts.v1", "summary_content.v1", "verification.v1"])
def test_model_output_schemas_cannot_supply_authorization_scope(summary, schema_id):
    payloads = {
        "facts.v1": {"facts": summary["facts"], "requirements": summary["requirements"]},
        "summary_content.v1": {
            key: summary[key] for key in ("executive_overview", "sections", "key_points")
        },
        "verification.v1": {"checked_claim_ids": [identity(11)], "findings": []},
    }
    model = OUTPUT_CONTRACTS[schema_id]
    assert model.model_validate_json(json.dumps(payloads[schema_id]))
    for scope_field in (
        "tenant_id",
        "project_id",
        "document_id",
        "processing_run_id",
        "profile",
        "workflow",
        "requested_by",
    ):
        with pytest.raises(ValidationError):
            model.model_validate({**payloads[schema_id], scope_field: identity(99)})


def test_supported_section_cannot_promote_unknown_requirement(summary):
    summary["sections"][1].update(fact_ids=[], requirement_ids=[identity(12)])
    with pytest.raises(ValidationError):
        TenderSummary.model_validate(summary)


def test_blocked_draft_can_preserve_explicit_unsupported_critical_fact(summary):
    summary["facts"][0]["status"] = "unsupported"
    summary["sections"][1]["status"] = "unsupported"
    summary["verification"]["verdict"] = "quality_blocked"
    assert TenderSummary.model_validate(summary).verification.verdict == "quality_blocked"


@pytest.mark.parametrize("field", ["messages", "allowed_tools"])
def test_collection_limits(generation_request, field):
    generation_request[field] = (
        [{"role": "user", "content": "x"}] * 33
        if field == "messages"
        else ["lookup_definition"] * 5
    )
    with pytest.raises(ValidationError):
        GenerationRequest.model_validate(generation_request)
