# Step 5: Build the Extraction Contract and Registry

## Step Status

Repository contract complete. Production extractor coverage and ingestion-worker release readiness
remain intentionally blocked until Steps 6 and 7 register and verify the real implementations.

## Objective

Define a format-neutral extraction boundary so PDF, DOCX, XLSX, and CSV implementations produce the
same ordered, source-traceable data. Keep parser-specific behavior outside orchestration, chunking,
embedding, and persistence.

## Prerequisites

- Step 3 schema contract available.
- Step 4 trusted temporary-file contract complete.
- Release format registry finalized as PDF, DOCX, XLSX, and CSV.
- Extraction limits available through validated settings.

## Package Structure

```text
backend/app/services/ingestion/
  __init__.py
  errors.py
  types.py
  registry.py
  extractors/
    __init__.py
    base.py
    pdf.py
    docx.py
    xlsx.py
    csv.py
```

## Core Types

Define immutable or validation-protected types.

### `ExtractedBlock`

Required fields:

- `ordinal`: monotonic source order;
- `text`: canonical extracted text before cross-block normalization;
- `block_type`: heading, paragraph, list item, table row, worksheet row, or equivalent;
- `page_number`: one-based PDF page when applicable;
- `sheet_name`: worksheet name when applicable;
- `row_start` and `row_end`: spreadsheet/CSV location when applicable;
- `heading_path`: ordered section labels;
- `extraction_method`: native or OCR;
- `metadata`: allowlisted, JSON-serializable source details.

### `ExtractionStatistics`

- detected format;
- page, worksheet, table, row, block, and character counts;
- native/OCR page counts;
- warnings as stable codes;
- extractor name and version.

### `ExtractionResult`

- ordered block sequence or bounded iterator;
- statistics;
- source content hash;
- confirmed format.

Do not include the temporary path, storage key, credentials, or parser exception object in persisted
metadata.

## Extractor Protocol

The protocol should express:

```python
class DocumentExtractor(Protocol):
    format_name: str
    version: str

    def supports(self, confirmed_format: str) -> bool: ...
    def extract(self, path: Path, limits: ExtractionLimits) -> ExtractionResult: ...
```

Parser work is blocking and CPU/memory intensive. Invoke extractors from the Celery worker, not the
FastAPI event loop. Use task/process isolation and time limits rather than merely wrapping unlimited
work in a thread.

## Registry Rules

- Selection uses the server-confirmed format, not a client MIME value.
- Exactly one extractor must support a format.
- Missing or ambiguous registrations fail worker readiness.
- Registry contents are static for the immutable release artifact.
- No plugin or parser is dynamically loaded from uploaded content.
- Extractor versions are explicit and stored with processing runs.

## Error Taxonomy

Define internal exceptions mapped to stable codes:

- unsupported format;
- encrypted document;
- malformed document;
- configured limit exceeded;
- no extractable content;
- OCR unavailable or failed;
- parser timeout;
- parser resource exhaustion;
- unexpected parser failure.

Unexpected exception text is logged only after sanitization and never returned to clients.

## Implementation Tasks

1. Create the ingestion package and common types.
2. Define extraction limits independently from global settings so they are easy to test.
3. Define the extractor and registry protocols.
4. Add stable errors and error-to-job mappings.
5. Add block validation: non-negative ordinal, allowed type, bounded text, valid locations.
6. Add result validation: unique monotonic ordinals and aggregate configured limits.
7. Add safe metadata allowlisting and JSON-serializability checks.
8. Add registry construction and readiness validation.
9. Create placeholder registrations only when the extractor implementation exists; never advertise a
   format backed by a stub.
10. Add fixture builders for parser unit tests.

## Files Expected to Change

- new ingestion package and modules listed above
- `backend/app/core/config.py` only if typed limit objects require adapters
- worker readiness
- unit tests for types, registry, and errors

## Test Matrix

- valid blocks for each source type;
- invalid ordinal, page, row range, metadata, or block type;
- result with out-of-order or duplicate ordinals;
- text and aggregate character limits;
- exactly one registry match per supported format;
- unsupported and ambiguous registry selection;
- extractor version recorded;
- exception mapping redacts paths and content;
- blocking extractor never runs in a FastAPI request handler.

## Security Checklist

- [x] Registry selection cannot be influenced by document text.
- [x] Dynamic imports/plugins are not permitted.
- [x] Metadata is explicitly allowlisted.
- [x] Temporary paths are not persisted or returned.
- [x] Parser exception text is sanitized.
- [x] All outputs remain bounded.
- [x] Uploaded content is treated only as data.

## Verification

Run the contract and registry unit suite with fake extractors. Demonstrate that an orchestration test
can swap a fake extractor through dependency construction without creating a second release runtime.

## Rollback

The contract can be introduced while ingestion remains disabled. If it changes before data is
persisted, update dependent parser branches together. After processing runs exist, extractor version
changes require a new version and reprocessing rather than mutating historical meaning.

## Exit Criteria

- [x] Common extraction types are validated and bounded.
- [ ] Registry has exactly one implementation per supported format. Pending real Steps 6 and 7
      implementations; the Step 5 production registry fails closed.
- [x] Error taxonomy is stable and sanitized.
- [x] Extractor versioning is explicit.
- [x] Contract tests pass without real storage or models.

## Handoff to Steps 6 and 7

Provide the extractor protocol, result/block types, limit object, registry mechanism, and error codes.
PDF/OCR and Office/CSV implementations must conform without extending persistence-specific behavior.

