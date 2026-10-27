# Step 6 Implementation Evidence

## Status

Repository implementation is complete as of 2026-10-25. Step 6 is not release-worker verified and
its release exit criteria are not complete. Approved exact OCR package versions were not available,
Docker and OCR executables were absent, and the available dependency audit reported known
vulnerabilities outside the new PDF dependency. Ingestion must remain disabled.

The release registry contains exactly one real PDF extractor. DOCX, XLSX, and CSV remain
unregistered, so overall ingestion-worker readiness intentionally fails closed pending Step 7.

## Changed Files

- `backend/pyproject.toml`
- `backend/Dockerfile`
- `backend/app/core/config.py`
- `backend/app/core/observability.py`
- `backend/app/cli.py`
- `backend/app/services/readiness.py`
- `backend/app/services/ingestion/types.py`
- `backend/app/services/ingestion/registry.py`
- `backend/app/services/ingestion/extractors/__init__.py`
- `backend/app/services/ingestion/extractors/pdf.py`
- `backend/.env.example`
- `backend/README.md`
- `backend/tests/pdf_fixtures.py`
- `backend/tests/pdf_extraction_fixtures.py`
- `backend/tests/test_pdf_extractor.py`
- `backend/tests/test_pdf_ocr.py`
- `backend/tests/test_pdf_ocr_runtime.py`
- `backend/tests/test_pdf_readiness.py`
- `backend/tests/test_pdf_packaging.py`
- Narrow updates to existing configuration, registry, readiness, architecture, and observability tests
- `docs/document-ingestion-vector-storage-steps/step-06-pdf-extraction-ocr.md`
- `docs/document-ingestion-vector-storage-steps/step-06-artifacts/implementation-evidence.md`

No React file, FastAPI route, database model, Alembic migration, vector service, chunking module,
job task, summary service, LLM integration, or Office/CSV extractor was changed for Step 6. The
working tree already contained unrelated changes in several of those areas; they were preserved.

## Extractor Contract

- Name: `pypdf-ocrmypdf`
- Version: `1.0.0`
- Registered format: `pdf`
- Native parser dependency: `pypdf==6.21.2`
- OCR implementation: fixed `ocrmypdf` executable invoking Tesseract through OCRmyPDF
- Source: only `configured-processing-root/<UUID>/input.pdf`, matching the Step 4 workspace shape
- Output: immutable Step 5 blocks, statistics, warnings, source SHA-256, and one-based pages

The extractor rejects non-files, symlinks, wrong filenames, paths outside the configured processing
root, non-UUID workspaces, encrypted files, invalid headers/structures, missing content, and bounded
limit failures. It computes SHA-256 by streaming the trusted file and never returns a local path.

## Bounds And Classification

Configured controls cover input bytes, pages, declared/encoded/decoded content-stream bytes,
per-block and aggregate characters, block count, parser deadline, OCR timeout, output bytes,
captured process-output bytes, CPU seconds, address-space bytes, and recursive workspace bytes.
Repository tests validate limit classification; Linux `prlimit`, container memory, and filesystem
behavior still require release-image evidence.

The versioned classifier uses these deterministic signals:

- No usable text plus an image: OCR required.
- An image plus fewer than `PDF_NATIVE_TEXT_MIN_CHARACTERS` usable characters: mixed.
- No usable text and no image: blank.
- Otherwise: native.

The default native threshold is 32 non-whitespace characters. Mixed-page deduplication uses only an
exact case-folded whitespace-collapsed key. It does not use fuzzy or semantic similarity. Repeated
margin removal requires at least three pages, the configured 0.8 page ratio, the configured page
band, exact text, and an explicit header/footer/confidential/copyright/page marker. Ambiguous and
meaningful repeated headings are retained.

## OCR Command And Cleanup

The command is an argument tuple with `shell=False`, fixed executable names, fixed flags, one job,
server-derived page numbers, the release-fixed `eng` language, and server-created input/output
paths. The process receives only a small fixed environment. Output and diagnostics are bounded;
diagnostics are never returned or logged. Timeout or interruption terminates and reaps the process
group. New OCR artifacts are removed while the trusted input and successful output are protected;
the enclosing Step 4 context removes the entire UUID workspace afterward.

OCR readiness checks exact configured OCRmyPDF and Tesseract version strings and the allowlisted
language without processing content. API readiness does not call this check. Worker failures expose
only `ocr_runtime`. Overall worker readiness then reaches `extractor_registry` and remains blocked
because Step 7 formats are absent.

## Packaging

The final `runtime` target is the API image and contains no OCR system package installation. The
separate `ocr-worker` target requires explicit exact build arguments for OCRmyPDF, Tesseract,
English language data, Ghostscript, and qpdf; omitted or unavailable values fail the build. It runs
as the existing non-root `wbs` account and provisions an owner-only processing root. No dependency
or language pack is downloaded at application runtime.

No exact OCR package value is recorded here because none was approved. The target was structurally
tested but not built. Transitive system-package closure, source snapshot, SBOM, and vulnerability
approval remain release gates.

## Verification Evidence

Focused PDF, OCR, readiness, packaging, architecture, metrics, and configuration suite:

```text
python -m pytest tests/test_pdf_extractor.py tests/test_pdf_ocr.py
  tests/test_pdf_ocr_runtime.py tests/test_pdf_readiness.py tests/test_pdf_packaging.py
  tests/test_extraction_architecture.py tests/test_ingestion_observability.py
  tests/test_database_config.py -q
98 passed, 1 skipped, 1 warning in 1.46s
```

The skipped test requires Windows symlink privileges. The warning is the pre-existing Starlette
`fastapi.testclient` deprecation warning.

Step 4 and Step 5 regression selection:

```text
python -m pytest <Step 4 and Step 5 regression paths> -q
141 passed, 1 skipped, 1 warning in 2.06s
```

Complete backend suite:

```text
python -m pytest -q
349 passed, 4 skipped, 1 warning in 40.37s
```

Quality and dependency consistency:

```text
python -m ruff check <changed Python paths>
All checks passed!

python -m ruff format --check <changed Python paths>
20 files already formatted

python -m pip check
No broken requirements found.

git diff --check
Exit 0; only existing line-ending notices were emitted.
```

Whole-repository Ruff lint passed. Whole-repository format verification still reports two historical
Alembic revisions outside Step 6; they were not reformatted because historical revisions and
unrelated changes are outside this scope.

## Vulnerability Result

`python -m pip_audit` completed against the current virtual environment and failed the release gate:

- `certifi 2026.7.22`: one reported advisory; fixed in `2026.10.19`.
- `cryptography 46.0.7`: reported advisories with fixes in later major versions.
- `pip 25.0.1`: reported advisories; this is environment tooling, not an application dependency.
- `pytest 8.4.2`: one reported advisory fixed in `9.0.3`; this is a development dependency.
- `wbs-api`: skipped because it is the local unpublished package.

No finding was reported for `pypdf 6.21.2`. The audit nevertheless fails overall. Updating
`cryptography` and `pytest` changes established authentication or development constraints and is
outside Step 6; those findings require a separately reviewed dependency upgrade. The unbuilt OCR
system packages were not scanned.

## Verified Repository Paths

- Native one-page, multi-page, rotated, blank-page, numeric, Unicode/ligature, and source-hash paths.
- Mocked scanned and mixed OCR paths with exact deduplication and retained distinct content.
- Encrypted, malformed, missing-content, page, stream, block, aggregate, output, timeout, process
  output, temporary disk, nonzero exit, unavailable runtime, and resource failure classifications.
- Process termination and artifact cleanup on timeout and forced interruption.
- Sensitive parser markers, paths, filenames, keys, endpoints, content, and raw output absent from
  stable errors, job mappings, logs, readiness, and metric labels.
- Exactly one PDF registration; no DOCX, XLSX, CSV, fake, or placeholder production registration.
- API readiness isolation and fail-closed worker OCR/registry readiness.

## External Release Gates

- Approve exact OCRmyPDF, Tesseract, English language-data, Ghostscript, qpdf, base-image, and full
  transitive package versions from a controlled package snapshot.
- Resolve or formally disposition the dependency audit findings, then rerun Python and image scans.
- Build both image targets and prove the API image has no OCR packages.
- Run the worker image as non-root with a read-only root filesystem and only the processing root
  writable.
- Verify actual clean scanned, mixed, encrypted, malformed, oversized, timeout, interruption, and
  cleanup fixtures with the installed OCR binaries and language data.
- Measure native pages/second, OCR pages/minute, peak memory, temporary disk, and maximum timeout.
- Verify CPU, memory, disk, process-group termination, and no residual child process under the
  release container runtime.
- Inspect release logs and metrics for content or infrastructure disclosure.
- Complete Step 7 and verify exactly one real DOCX, XLSX, and CSV extractor.

## Residual Risks

- OCR behavior is mock-verified only; real OCR accuracy and binary failure behavior remain unknown.
- `pypdf` materializes a decoded content stream before the post-decode byte check. The release
  worker memory/container limit is therefore a mandatory defense and must be proven before release.
- Native parser deadline checks occur between page operations; container/task process isolation is
  required to terminate a parser call that blocks inside the library.
- System-package dependency closure is not reproducibly locked until exact approved build inputs and
  the approved package snapshot are recorded.
- Overall ingestion-worker readiness remains intentionally blocked until Step 7.
