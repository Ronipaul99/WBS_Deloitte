from io import BytesIO

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def _pdf_with_content_stream(content: bytes) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(output)
    return output.getvalue()


def _escape_pdf_literal(value: str) -> bytes:
    encoded = value.encode("latin-1")
    return encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def text_pages_pdf_bytes(
    pages: list[list[tuple[str, int]]],
    *,
    rotated_pages: frozenset[int] = frozenset(),
    image_pages: frozenset[int] = frozenset(),
) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    for page_number, positioned_lines in enumerate(pages, start=1):
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})}
        )
        commands: list[bytes] = []
        for text, y_position in positioned_lines:
            commands.append(
                b"BT /F1 12 Tf 72 "
                + str(y_position).encode("ascii")
                + b" Td ("
                + _escape_pdf_literal(text)
                + b") Tj ET"
            )
        if page_number in image_pages:
            commands.append(
                b"q 10 0 0 10 72 360 cm BI /W 1 /H 1 /CS /RGB /BPC 8 ID \x00\x00\x00 EI Q"
            )
        stream = DecodedStreamObject()
        stream.set_data(b"\n".join(commands))
        page[NameObject("/Contents")] = writer._add_object(stream)
        if page_number in rotated_pages:
            page.rotate(90)
    writer.write(output)
    return output.getvalue()


def text_pdf_bytes() -> bytes:
    pdf = text_pages_pdf_bytes([[("Synthetic project scope", 720)]])
    assert PdfReader(BytesIO(pdf), strict=True).pages[0].extract_text() == "Synthetic project scope"
    return pdf


def scanned_pdf_bytes() -> bytes:
    pdf = _pdf_with_content_stream(
        b"q 10 0 0 10 72 720 cm BI /W 1 /H 1 /CS /RGB /BPC 8 ID \x00\x00\x00 EI Q"
    )
    assert PdfReader(BytesIO(pdf), strict=True).pages[0].extract_text() == ""
    return pdf


def compressed_content_pdf_bytes(decoded_size: int) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    stream = DecodedStreamObject()
    stream.set_data(b"%" + b"x" * decoded_size)
    page[NameObject("/Contents")] = writer._add_object(stream.flate_encode())
    writer.write(output)
    return output.getvalue()


def encrypted_pdf_bytes() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("synthetic-test-password")
    writer.write(output)
    return output.getvalue()


def pad_pdf_to_size(pdf: bytes, size: int) -> bytes:
    if size < len(pdf) + 2:
        raise ValueError("Requested fixture size is too small.")
    return pdf + b"\n%" + (b"x" * (size - len(pdf) - 2))
