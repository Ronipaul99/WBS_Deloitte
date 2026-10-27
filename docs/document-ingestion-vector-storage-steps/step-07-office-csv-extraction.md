# Step 7: Implement DOCX, XLSX, and CSV Extraction

## Step Status

Repository implementation complete as of 2026-10-25. Release-worker verification remains pending
because Docker is unavailable in the current environment and the pinned parser dependencies still
require organizational approval and release-image vulnerability review. Document ingestion must
remain disabled until those external gates and the remaining execution-plan steps are complete.

## Objective

Extract structured, ordered, source-referenced blocks from modern Word documents, Excel workbooks,
and CSV files without executing macros, formulas, external links, or embedded objects.

## Prerequisites

- Step 5 contract and registry complete.
- `python-docx`, `openpyxl`, and `defusedxml` versions approved and pinned.
- Release formats finalized without legacy `.doc` or `.xls` unless conversion was separately
  approved.
- Safe fixtures containing headings, tables, formulas, multiple sheets, encodings, and malformed
  archives available.

## DOCX Extraction Design

Required behavior:

- iterate paragraphs and tables in document order;
- capture heading styles into a heading path;
- preserve numbered and bulleted list text;
- convert each table row into a deterministic textual block;
- retain table headers and cell ordering;
- ignore images unless future OCR scope explicitly adds them;
- never fetch external relationships;
- never execute embedded content;
- reject encrypted, macro-enabled, malformed, or over-limit packages.

Because high-level `python-docx` collections can separate paragraphs and tables, implement or use a
tested document-order iterator rather than concatenating all paragraphs before all tables.

## XLSX Extraction Design

Load with read-only and data-only behavior. Required behavior:

- process allowlisted visible/hidden sheet behavior according to product policy;
- preserve sheet name and one-based row range;
- identify a bounded header row for each contiguous region;
- emit deterministic row blocks;
- repeat headers later during chunking, not by modifying raw extracted rows;
- use cached formula results only and never evaluate formulas;
- enforce worksheet, row, column, cell, character, merged-range, and archive limits;
- explicitly close the workbook;
- do not fetch external links.

If worksheet dimensions are clearly incorrect, reset or correct them only within configured bounds
and record a warning.

## CSV Extraction Design

Required behavior:

- support UTF-8 with optional BOM for the initial release;
- reject undecodable input with a stable code;
- detect delimiter only from comma, semicolon, tab, or pipe;
- cap field length, column count, row count, and total characters;
- preserve normalized headers and one-based data row locations;
- handle quoted delimiters and embedded newlines;
- do not silently remove formula-like prefixes from canonical text.

Formula-injection neutralization belongs to any later spreadsheet export or HTML preview rendering,
not canonical ingestion.

## Implementation Tasks

1. Add pinned parsing dependencies.
2. Implement document-order DOCX iteration.
3. Implement heading-path and list/table block creation.
4. Implement read-only/data-only XLSX iteration with explicit close.
5. Implement bounded region/header detection for workbooks.
6. Implement allowlisted CSV dialect detection and UTF-8 decoding.
7. Enforce shared extraction limits and format-specific limits.
8. Produce stable statistics and warning codes.
9. Register each extractor only after mandatory tests pass.
10. Remove `.doc` and `.xls` from every advertised format location if not already removed.

## Files Expected to Change

- `backend/pyproject.toml`
- `backend/app/services/ingestion/extractors/docx.py`
- `backend/app/services/ingestion/extractors/xlsx.py`
- `backend/app/services/ingestion/extractors/csv.py`
- extractor registry
- UI/backend format allowlists if still inconsistent
- Office/CSV fixtures and tests

## Test Matrix

DOCX:

- headings and paragraphs;
- numbered and bulleted lists;
- tables between paragraphs;
- merged table cells;
- headers/footers according to documented policy;
- image-only content;
- external relationship;
- macro-enabled or encrypted input;
- ZIP bomb/archive limits;
- malformed XML/package.

XLSX:

- single and multiple worksheets;
- empty/hidden sheets;
- formulas with and without cached values;
- merged cells;
- sparse worksheet;
- incorrect worksheet dimensions;
- maximum rows/columns/cells;
- external links;
- macro-enabled/encrypted input;
- malformed or unsafe archive.

CSV:

- comma, semicolon, tab, and pipe delimiters;
- quoted delimiter and embedded newline;
- UTF-8 BOM;
- missing/duplicate headers;
- long fields and too many columns/rows;
- invalid encoding;
- formula-like cells retained canonically;
- empty file.

## Security Checklist

- [x] XML parser protections are active.
- [x] Archive entry count, expansion, and ratio limits remain enforced.
- [x] Macros and legacy binary formats are not accepted silently.
- [x] External relationships/links are never fetched by repository implementations.
- [x] Formulas are never evaluated.
- [x] Workbooks are explicitly closed.
- [x] All row, column, field, and character counts are bounded.
- [x] Parser errors do not expose content or temporary paths.

## Verification

Run all extractor tests inside the release worker image. Compare source order and metadata manually for
at least one representative DOCX, XLSX, and CSV fixture. Confirm no network access is attempted while
opening files with external links.

## Rollback

Remove an affected format from the UI and backend allowlists if its extractor cannot meet release
criteria. Do not accept a format and then store an empty or misleading successful ingestion.

## Exit Criteria

- [x] DOCX preserves headings, paragraph/table order, lists, and source metadata.
- [x] XLSX preserves sheet/row provenance without formula execution.
- [x] CSV preserves headers/rows with bounded dialect handling.
- [x] Unsupported legacy and macro-enabled formats are consistently rejected.
- [ ] All format-specific limit and abuse tests pass in the release image.
- [x] Extractor versions and warnings are recorded.

## Handoff to Step 8

Provide ordered blocks, heading/sheet/row provenance, extractor versions, statistics, warnings, and
stable failures. Step 8 applies shared normalization and model-aware chunking.

