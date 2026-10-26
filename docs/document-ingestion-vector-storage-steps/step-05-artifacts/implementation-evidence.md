# Step 5 Implementation Evidence

## Status

Repository contract implementation is complete as of 2026-10-25. Production extractor coverage
and ingestion-worker release readiness remain intentionally blocked until Steps 6 and 7 provide
and verify exactly one real extractor for PDF, DOCX, XLSX, and CSV.

## Changed Files

- `backend/app/services/ingestion/types.py`
- `backend/app/services/ingestion/registry.py`
- `backend/app/services/ingestion/errors.py`
- `backend/app/services/ingestion/extractors/__init__.py`
- `backend/app/services/ingestion/extractors/base.py`
- `backend/app/services/readiness.py`
- `backend/app/core/config.py`
- `backend/.env.example`
- `backend/README.md`
- `backend/tests/extraction_fixtures.py`
- `backend/tests/test_extraction_types.py`
- `backend/tests/test_extractor_registry.py`
- `backend/tests/test_extraction_errors.py`
- `backend/tests/test_extraction_readiness.py`
- `backend/tests/test_extraction_architecture.py`
- `backend/tests/test_ingestion_readiness.py`
- `docs/document-ingestion-vector-storage-steps/step-05-extraction-contract.md`
- `docs/document-ingestion-vector-storage-steps/step-05-artifacts/implementation-evidence.md`

No React file, API route, database model, Alembic migration, persistence service, or dependency
manifest was changed for Step 5.

## Contract Controls

`ConfirmedDocumentFormat` accepts only exact server-confirmed `pdf`, `docx`, `xlsx`, and `csv`
values. The suffix adapter accepts only the corresponding exact lowercase suffixes. Selection does
not consume filenames, MIME values, document text, metadata, paths, or parser guesses.

`ExtractionLimits` is immutable and independent of global settings. It bounds pages, worksheets,
rows, aggregate and per-block characters, blocks, heading depth and labels, warnings, metadata
fields/depth/value/list sizes, and sheet names. Its settings adapter reuses the existing release
limits and caps the effective per-block limit at the aggregate limit.

`ExtractedBlock`, `ExtractionStatistics`, and `ExtractionResult` are frozen, defensively copy all
caller collections, and expose immutable ordered tuples. Validation covers source locations,
ordinals, counts, hashes, format agreement, aggregate sizes, extractor identity, and warning codes.
Result construction revalidates blocks and statistics against the limits supplied at the result
boundary.

Metadata top-level keys are explicitly limited to `attributes`, `column_index`, `column_name`,
`coordinates`, `is_header`, `list_level`, `page_label`, `source_kind`, and `table_index`. Nested keys
use a bounded safe syntax and reject path, filename, storage, object, credential, endpoint, error,
tenant, project, and document concepts. Values are bounded JSON scalars, mappings, or sequences;
bytes, paths, arbitrary objects, NaN, infinity, control characters, excessive nesting, and
oversized collections are rejected. Validated metadata remains compatible with the standard JSON
encoder.

## Extractor Protocol And Registry

`DocumentExtractor` is a synchronous, dependency-injectable protocol with explicit format, name,
version, support, and extraction contracts. No FastAPI route imports or invokes it.

`ExtractorRegistry` copies registrations into a tuple, validates format/name/version, rejects the
same object registered twice, and requires exactly one support match. It uses no dynamic imports,
entry points, filesystem discovery, `eval`, or `exec`. Test fakes exist only under `backend/tests`.
The production registry is explicitly empty; it advertises no stub or fabricated implementation.

Worker readiness validates registry completeness after the existing Redis, ClamAV, and model-path
checks. Missing or ambiguous coverage reports only `extractor_registry`. API readiness neither
constructs the registry nor performs blocking extraction work.

## Error Contract

The Step 4 input error contract remains unchanged. Step 5 adds the documented stable extraction
codes with fixed messages and explicit retryability. The typed job mapping contains only the stable
code, retryable flag, and safe message. Unexpected exceptions are mapped to
`DOCUMENT_EXTRACTION_FAILED`; logs retain only the exception type category and omit exception text,
content, locations, filenames, object details, and endpoints.

## Verification Evidence

Focused contract, registry, error, readiness, architecture, and existing readiness tests:

```text
python -m pytest tests/test_extraction_types.py tests/test_extractor_registry.py
  tests/test_extraction_errors.py tests/test_extraction_readiness.py
  tests/test_extraction_architecture.py tests/test_ingestion_readiness.py -q
95 passed, 1 warning in 0.51s
```

Step 4 regression suite:

```text
python -m pytest tests/test_object_storage.py tests/test_malware_scanning.py
  tests/test_ingestion_workspace.py tests/test_ingestion_readiness.py
  tests/test_ingestion_observability.py tests/test_document_input_preparation.py -q
43 passed, 1 skipped, 1 warning in 1.54s
```

Complete backend suite:

```text
python -m pytest -q
307 passed, 3 skipped, 1 warning in 36.18s
```

The skips are the two opt-in PostgreSQL/pgvector integration tests that require approved disposable
database credentials and the Windows symlink test that requires symlink privileges. The warning is
an existing Starlette deprecation warning from `fastapi.testclient`.

Quality checks:

```text
python -m ruff check <14 changed Python paths>
All checks passed!

python -m ruff format --check <14 changed Python paths>
14 files already formatted

python -m pip check
No broken requirements found.

git diff --check
Exit 0; only existing LF-to-CRLF checkout notices were emitted.
```

Architecture tests verified immutability, metadata allowlisting, result and count bounds, exact
format selection, missing and ambiguous registry behavior, exception redaction, an empty production
registry, and the API/worker readiness separation. No parser package or Step 5 dependency was added.

## Remaining Gates

- Step 6 must implement and verify one real PDF extractor and its approved OCR behavior.
- Step 7 must implement and verify one real DOCX, XLSX, and CSV extractor each.
- The release registry must then explicitly register exactly one implementation per required format.
- Worker readiness must be rerun in the release image after those registrations are present.
- Parser process isolation, execution timeouts, and resource enforcement remain later worker work.

## Residual Risks

- No untrusted document has been parsed in Step 5, by design; parser-specific behavior is unverified.
- Contract evolution after persisted processing runs exist must preserve extractor version history.
- Real extractors may expose additional safe traceability needs; those must be reviewed against the
  allowlist and bounds instead of bypassing the common contract.
