from io import BytesIO
from uuid import uuid4

from extraction_fixtures import extraction_limits
from pdf_extraction_fixtures import FakeOcrRunner, pdf_policy
from pdf_fixtures import text_pages_pdf_bytes
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.services.ingestion.extractors.pdf import PdfExtractor
from app.services.ingestion.extractors.pdf_layout import heading_level, page_structure
from app.services.ingestion.types import ExtractedBlockType, ExtractionWarningCode


def ruled_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(612, 792)
    fonts = DictionaryObject()
    for key, name in (("/F1", "/Helvetica"), ("/F2", "/Helvetica-Bold")):
        fonts[NameObject(key)] = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject(name),
                }
            )
        )
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): fonts})
    commands = [b"BT /F2 14 Tf 50 740 Td (7. SECURITY DEPOSIT) Tj ET"]
    for x in (50, 240, 550):
        commands.append(f"{x} 590 m {x} 710 l S".encode())
    for y in (590, 630, 670, 710):
        commands.append(f"50 {y} m 550 {y} l S".encode())
    for y, font, left, right in (
        (690, "F2", "Option", "Deposit"),
        (650, "F1", "One unit", "100 currency units"),
        (610, "F1", "Two units", "200 currency units"),
    ):
        commands.extend(
            [
                f"BT /{font} 12 Tf 60 {y} Td ({left}) Tj ET".encode(),
                f"BT /{font} 12 Tf 250 {y} Td ({right}) Tj ET".encode(),
            ]
        )
    stream = DecodedStreamObject()
    stream.set_data(b"\n".join(commands))
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def extract(tmp_path, content):
    work = tmp_path / str(uuid4())
    work.mkdir()
    source = work / "input.pdf"
    source.write_bytes(content)
    return PdfExtractor(pdf_policy(processing_root=tmp_path), FakeOcrRunner()).extract(
        source,
        extraction_limits(),
    )


def test_ruled_table_preserves_pairs_headers_and_heading(tmp_path):
    result = extract(tmp_path, ruled_pdf())
    rows = [b for b in result.blocks if b.block_type is ExtractedBlockType.TABLE_ROW]
    assert [b.text for b in rows] == [
        "Option | Deposit",
        "One unit | 100 currency units",
        "Two units | 200 currency units",
    ]
    assert rows[0].metadata["is_header"] is True
    assert all(b.heading_path == ("7. SECURITY DEPOSIT",) for b in rows)
    assert result.statistics.table_count == 1


def test_variable_margin_numbers_removed_but_body_mentions_retained(tmp_path):
    result = extract(
        tmp_path,
        text_pages_pdf_bytes(
            [
                [(f"Page {i} of 3", 30), ("Body mentions Page 1 of 3 in a clause", 500)]
                for i in range(1, 4)
            ]
        ),
    )
    assert len(result.blocks) == 3
    assert all("Body mentions" in b.text for b in result.blocks)
    assert sum(len(b.metadata["removed_margins"]) for b in result.blocks) == 3
    assert ExtractionWarningCode.REPEATED_MARGIN_REMOVED in result.statistics.warning_codes


def test_layout_coverage_mismatch_returns_no_candidate(tmp_path):
    import pdfplumber

    path = tmp_path / "fixture.pdf"
    path.write_bytes(ruled_pdf())
    with pdfplumber.open(path) as pdf:
        result, headings = page_structure(
            pdf.pages[0],
            source_lines=("Required text that the layout parser lost",),
            removed_margins=(),
            headings=(),
            maximum_blocks=1000,
            maximum_characters=10000,
            maximum_heading_depth=16,
            maximum_heading_characters=500,
        )
        assert result is None and headings == ()


def test_numbered_body_text_is_not_automatically_a_heading():
    assert heading_level("3.1 ordinary text in the body", False) is None
    assert heading_level("3.1 Eligibility", True) == 4
    assert heading_level("GLOSSARY", True) == 1


def test_glossary_continuation_retains_table_identity_and_row_context(tmp_path):
    writer = PdfWriter()
    for index in range(2):
        page = PdfReader(BytesIO(ruled_pdf())).pages[0]
        stream = DecodedStreamObject()
        stream.set_data(page.get_contents().get_data().replace(b"7. SECURITY DEPOSIT", b"GLOSSARY"))
        page[NameObject("/Contents")] = stream
        if index == 0:
            page.add_transformation(Transformation().translate(ty=-550))
        writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    result = extract(tmp_path, output.getvalue())
    rows = [b for b in result.blocks if b.block_type is ExtractedBlockType.TABLE_ROW]
    assert len(rows) == 6
    assert len({b.metadata["table_index"] for b in rows}) == 1
    assert [b.metadata["row_index"] for b in rows] == list(range(1, 7))
    assert [b.heading_path[-1] for b in rows] == ["Option", "One unit", "Two units"] * 2
    assert all(b.heading_path[0] == "GLOSSARY" for b in rows)
    assert rows[0].metadata["is_header"] and rows[3].metadata["is_header"]
