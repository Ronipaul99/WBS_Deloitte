import pytest

from app.services.ingestion.normalization import normalize_extracted_text


def test_normalization_is_conservative_and_idempotent() -> None:
    source = (
        "REQ-1\r\n\r\n\r\n1. Do not exclude 25% at $10.50/kg\u00a0\r"
        "Assumption: finish 2026-10-25.\x00"
    )

    normalized = normalize_extracted_text(source)

    assert normalized == (
        "REQ-1\n\n1. Do not exclude 25% at $10.50/kg\nAssumption: finish 2026-10-25."
    )
    assert normalize_extracted_text(normalized) == normalized


@pytest.mark.parametrize(
    "source, expected",
    [
        ("A\t |  |\u2003C", "A |  | C"),
        ("• Item\n2. Requirement", "• Item\n2. Requirement"),
        ("Risk: must not proceed", "Risk: must not proceed"),
    ],
)
def test_normalization_preserves_structure_and_table_positions(source: str, expected: str) -> None:
    assert normalize_extracted_text(source) == expected


def test_normalization_rejects_non_text_without_disclosing_value() -> None:
    with pytest.raises(RuntimeError) as error:
        normalize_extracted_text(object())

    assert "object" not in str(error.value)
