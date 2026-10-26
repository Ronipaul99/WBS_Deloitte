# Step 6: Implement PDF Extraction and OCR

## Step Status

Repository implementation complete; release-worker verification blocked.

Implemented and mock-verified on 2026-10-25. Exact approved OCR system-package versions, the
release container runtime, language-data inspection, resource/performance measurements, and a clean
dependency vulnerability gate remain unavailable or unresolved. See
`step-06-artifacts/implementation-evidence.md` for the evidence and blockers. Step 7 formats remain
intentionally unregistered.

## Objective

Extract ordered, page-referenced blocks from both text-based and scanned PDFs while bounding CPU,
memory, page count, content-stream size, OCR duration, and temporary artifacts.

## Prerequisites

- Step 5 contract and registry complete.
- `pypdf`, OCRmyPDF, and Tesseract versions approved and pinned.
- Worker image includes required OCR system packages and language data.
- OCR and parser resource limits approved.
- Synthetic text, scanned, mixed, encrypted, and hostile PDF fixtures available.

## Extraction Strategy

1. Open the trusted scanned file with `pypdf`.
2. Reject encryption and page count above the configured maximum.
3. Inspect each page under content-stream limits.
4. Extract native text page by page.
5. Classify pages as native, mixed, or OCR-required using a documented deterministic threshold.
6. If no OCR is required, return native ordered blocks.
7. If OCR is required, create OCR output inside the processing-run temporary workspace.
8. Run OCRmyPDF/Tesseract with timeout, page, language, and resource controls.
9. Re-open OCR output and extract searchable text.
10. Deduplicate native and OCR text for mixed pages.
11. Return extraction statistics and warnings.
12. Remove OCR intermediates in the workspace cleanup path.

## Native Text Rules

- Preserve one-based page number.
- Retain paragraph/line grouping conservatively.
- Normalize only parser artifacts required to create valid blocks; broader normalization belongs to
  Step 8.
- Record extraction method as `native`.
- Do not infer headings solely from font size unless the heuristic is deterministic, tested, and
  versioned.
- Do not omit pages silently. Empty pages produce a warning or trigger OCR classification.

## OCR Rules

- OCR runs only when the configured classifier indicates it is needed.
- OCR language packs are allowlisted and fixed by release configuration.
- The worker never invokes a shell with user-controlled arguments.
- OCR output cannot overwrite the original input.
- Record extraction method as `ocr` for OCR-derived blocks.
- Preserve original page numbering.
- Reject OCR output that remains empty or exceeds extraction limits.

## Header and Footer Handling

Detect repeated headers/footers only after collecting page candidates. Remove text only when it:

- occurs in a consistent page region or position signal available from the parser;
- repeats on a configured proportion of pages;
- is not a meaningful section heading, requirement, or table header;
- is covered by regression fixtures.

When uncertain, retain the content. False retention is safer than deleting project scope.

## Implementation Tasks

1. Add pinned `pypdf` and approved OCR dependencies.
2. Add OCR system packages and language data to the worker image only.
3. Implement the PDF extractor against the Step 5 contract.
4. Implement page and content-stream prechecks.
5. Implement native page extraction.
6. Implement deterministic OCR-required classification.
7. Implement OCR invocation with fixed arguments and bounded resources.
8. Implement mixed-page deduplication.
9. Add repeated-header/footer handling with explicit thresholds.
10. Generate extraction statistics and warnings.
11. Register the extractor only after all mandatory fixture tests pass.
12. Add parser/OCR metrics without content labels.

## Files Expected to Change

- `backend/pyproject.toml`
- `backend/Dockerfile`
- `backend/app/services/ingestion/extractors/pdf.py`
- registry construction
- PDF fixtures and tests
- worker readiness for OCR binaries/language data

## Test Matrix

Functional:

- one-page text PDF;
- multi-page text PDF;
- scanned PDF;
- mixed native/scanned pages;
- rotated page;
- blank page inside a valid document;
- repeated header/footer;
- numeric tables retained as text;
- Unicode and ligature content.

Failure and abuse:

- encrypted PDF;
- invalid header or trailer;
- page count above limit;
- extremely large content stream;
- OCR timeout;
- missing OCR binary/language data;
- OCR output still empty;
- temporary disk exhaustion;
- task cancellation during OCR;
- parser exception containing a local path or source snippet.

## Security Checklist

- [ ] PDF and OCR dependencies are pinned and scanned.
- [x] OCR command arguments contain no user-controlled shell content.
- [ ] Page, stream, character, time, memory, and disk limits are enforced.
- [x] Encrypted PDFs fail closed.
- [x] External references are not fetched.
- [x] OCR output remains in the validated temporary workspace.
- [x] Logs and metrics contain no extracted text.

## Performance Targets

Set targets using representative fixtures and worker capacity. At minimum record:

- native extraction pages per second;
- OCR pages per minute;
- peak worker memory;
- temporary disk use;
- timeout behavior at the configured maximum.

Do not publish an unsupported SLA before measurements exist.

## Verification

Run the PDF unit/abuse suite inside the release worker image, not only on a developer host. Confirm
OCR binaries, language packs, non-root permissions, filesystem cleanup, and resource controls.

## Rollback

Disable ingestion or scanned-PDF processing if OCR regresses. Do not silently treat an image-only PDF
as successfully extracted. Native PDF extraction may remain enabled only if product behavior and
configuration accurately disclose scanned-PDF unavailability.

## Exit Criteria

- [x] Native and mock-OCR scanned fixtures produce ordered page-linked blocks.
- [x] Mixed pages avoid material duplication under deterministic exact deduplication.
- [x] Empty, encrypted, malformed, and over-limit files fail safely in repository tests.
- [ ] OCR runs non-root with fixed arguments and bounded resources.
- [ ] Parser and OCR tests pass inside the release image.
- [x] Extraction statistics and safe metrics are recorded.

## Handoff to Step 8

Provide ordered PDF blocks, page/extraction-method metadata, extractor version, statistics, warnings,
and stable failures. Step 8 normalizes and chunks these blocks without losing page provenance.

