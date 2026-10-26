"""Bounded native-PDF structure, reconciled against the guarded pypdf text.

Layout is advisory: a page whose character coverage cannot be reconciled keeps
its original text and emits a warning. No OCR or external services are used here.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.services.ingestion.types import ExtractedBlockType


@dataclass(frozen=True, slots=True)
class LayoutBlock:
    text: str
    block_type: ExtractedBlockType
    heading_path: tuple[str, ...]
    metadata: dict[str, Any]


def character_coverage(text: str) -> Counter:
    return Counter(character for character in text if not character.isspace())


def _inside(obj: dict, box: tuple) -> bool:
    x = (obj["x0"] + obj["x1"]) / 2
    y = (obj["top"] + obj["bottom"]) / 2
    return box[0] <= x < box[2] and box[1] <= y < box[3]


def _bold(chars: list) -> bool:
    visible = [c for c in chars if str(c.get("text", "")).strip()]
    return (
        bool(visible)
        and sum("bold" in str(c.get("fontname", "")).lower() for c in visible) / len(visible)
        >= 0.65
    )


def heading_level(text: str, bold: bool) -> int | None:
    if not bold or len(text) > 160 or not any(c.isalpha() for c in text):
        return None
    if re.match(r"^(SECTION|ANNEX(?:URE)?|SCHEDULE|GLOSSARY)\b", text, re.I):
        return 1
    if re.match(r"^PART\s+[A-Z0-9]+\b", text, re.I):
        return 2
    if re.match(r"^\d+\.\d+\s+\D", text):
        return 4
    if re.match(r"^\d+\.?\s+\D", text):
        return 3
    return None


def page_structure(
    page: Any,
    *,
    source_lines: tuple[str, ...],
    removed_margins: tuple[str, ...],
    headings: tuple[tuple[int, str], ...],
    maximum_blocks: int,
    maximum_characters: int,
    maximum_heading_depth: int,
    maximum_heading_characters: int,
) -> tuple[list[LayoutBlock] | None, tuple[tuple[int, str], ...]]:
    """Return None on ambiguous coverage; never discard the guarded source text."""
    if page.rotation % 360:
        return None, headings
    if len(page.chars) > min(maximum_characters, 100_000) or len(page.edges) > min(
        maximum_blocks * 4, 2000
    ):
        return None, headings
    tables = []
    for table in page.find_tables():
        # Underlines and boxed paragraphs are not multi-column tables.
        usable = [
            [cell for cell in row.cells if cell and cell[2] - cell[0] >= 12] for row in table.rows
        ]
        usable = [row for row in usable if len(row) >= 2]
        if not usable:
            continue
        if (
            len(table.cells) > min(maximum_blocks, 2000)
            or len(tables) >= 100
            or len(page.chars) * len(table.cells) > 2_000_000
        ):
            return None, headings
        # A full data row avoids tiny spurious cells in merged/multiline headers.
        template = max(
            usable, key=lambda cells: max(c[3] for c in cells) - min(c[1] for c in cells)
        )
        edges = [template[0][0], *[cell[2] for cell in template]]
        if any(b - a < 12 for a, b in zip(edges, edges[1:], strict=False)):
            return None, headings
        bands: list[list[float]] = []
        for row in table.rows:
            top, bottom = row.bbox[1], row.bbox[3]
            if bands and top < bands[-1][1] - 1:
                bands[-1][1] = max(bottom, bands[-1][1])
            else:
                bands.append([top, bottom])
        tables.append((table.bbox, edges, bands))
    # Overlapping table detections are ambiguous, not separate source regions.
    for i, (box, _, _) in enumerate(tables):
        if any(
            min(box[2], other[2]) - max(box[0], other[0]) > 1
            and min(box[3], other[3]) - max(box[1], other[1]) > 1
            for other, _, _ in tables[i + 1 :]
        ):
            return None, headings
    events: list[tuple[float, float, str, ExtractedBlockType, dict, bool, str]] = []
    outside = page.filter(
        lambda obj: (
            obj.get("object_type") != "char" or not any(_inside(obj, box) for box, _, _ in tables)
        )
    )
    removed = Counter(removed_margins)
    for line in outside.extract_text_lines(return_chars=True, expand_ligatures=False):
        value = line["text"].strip()
        is_margin = line["top"] < page.height * 0.12 or line["bottom"] > page.height * 0.88
        if is_margin and removed[value]:
            removed[value] -= 1
            continue
        events.append(
            (
                line["top"],
                line["x0"],
                value,
                ExtractedBlockType.PARAGRAPH,
                {},
                _bold(line["chars"]),
                value,
            )
        )
    for table_number, (box, edges, bands) in enumerate(tables):
        for row_number, (top, bottom) in enumerate(bands):
            cells = []
            for left, right in zip(edges, edges[1:], strict=False):
                region = (left, top, right, bottom)
                cropped = page.filter(
                    lambda obj, region=region: (
                        obj.get("object_type") != "char" or _inside(obj, region)
                    )
                )
                cells.append(" ".join((cropped.extract_text(expand_ligatures=False) or "").split()))
            if not any(cells):
                continue
            chars = [char for char in page.chars if _inside(char, (box[0], top, box[2], bottom))]
            metadata = {
                "table_index": page.page_number * 1000 + table_number,
                "is_header": row_number == 0 and _bold(chars),
                "row_index": row_number + 1,
                "coordinates": [round(value, 2) for value in box],
                "column_count": len(edges) - 1,
            }
            events.append(
                (
                    top,
                    box[0],
                    " | ".join(cells),
                    ExtractedBlockType.TABLE_ROW,
                    metadata,
                    False,
                    " ".join(cells),
                )
            )
    if len(events) > maximum_blocks:
        return None, headings
    if character_coverage("".join(source_lines)) != character_coverage(
        "".join(event[6] for event in events)
    ):
        return None, headings
    active = list(headings)
    result = []
    for _, _, value, kind, metadata, bold, _ in sorted(events, key=lambda e: (e[0], e[1])):
        level = heading_level(value, bold) if kind != ExtractedBlockType.TABLE_ROW else None
        if level is not None and len(value) <= maximum_heading_characters:
            active = [(old_level, label) for old_level, label in active if old_level < level]
            if len(active) < maximum_heading_depth:
                active.append((level, value))
                kind = ExtractedBlockType.HEADING
        context = tuple(label for _, label in active)
        if (
            kind is ExtractedBlockType.TABLE_ROW
            and metadata.get("column_count") == 2
            and any(label.upper() == "GLOSSARY" for label in context)
        ):
            term = value.split(" | ", 1)[0].strip()
            if (
                term
                and len(term) <= maximum_heading_characters
                and len(context) < maximum_heading_depth
            ):
                context = (*context, term)
        result.append(LayoutBlock(value, kind, context, metadata))
    return result, tuple(active)
