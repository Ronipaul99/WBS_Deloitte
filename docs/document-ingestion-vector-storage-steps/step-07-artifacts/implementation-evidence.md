# Step 7 Implementation Evidence

## Status

The Step 7 repository implementation is complete as of 2026-10-25. Office/CSV extraction is not
release-worker verified. Docker is unavailable in this environment, the exact dependency pins still
require organizational approval, and release-image vulnerability, resource, network-isolation, and
performance checks remain external gates. Document ingestion must remain disabled.

The repository release registry now contains exactly one real extractor for each confirmed format:
`pdf`, `docx`, `xlsx`, and `csv`. Registry completeness passes. Overall worker readiness still
depends on Redis, private object storage, ClamAV, OCR, the packaged embedding model, and the release
configuration established by other steps.

## Changed Files

- `backend/pyproject.toml`
- `backend/app/core/config.py`
- `backend/app/core/observability.py`
- `backend/app/services/ingestion/types.py`
- `backend/app/services/ingestion/registry.py`
- `backend/app/services/ingestion/extractors/_common.py`
- `backend/app/services/ingestion/extractors/docx.py`
- `backend/app/services/ingestion/extractors/xlsx.py`
- `backend/app/services/ingestion/extractors/csv.py`
- `backend/app/api/routes/templates.py`
- `backend/.env.example`
- `backend/README.md`
- `backend/tests/extraction_fixtures.py`
- `backend/tests/test_office_csv_extractors.py`
- `backend/tests/test_office_csv_packaging.py`
- Narrow registry, readiness, architecture, observability, and regression test updates
- `WBS_UI/src/views/CreateWbsScreen.tsx`
- `WBS_UI/tests/create-wbs.spec.ts`
- `docs/document-ingestion-vector-storage-steps/step-07-office-csv-extraction.md`
- This evidence file

No FastAPI extraction route, database model, migration, ingestion task, chunking module, embedding
runtime, vector persistence/search service, summary, LLM, or agentic workflow was added.

## Dependencies And Extractor Identity

Repository dependency pins and installed test-environment versions:

- `python-docx==1.2.0`; extractor `python-docx`, version `1.0.0`, format `docx`.
- `openpyxl==3.1.5`; extractor `openpyxl`, version `1.0.0`, format `xlsx`.
- `defusedxml==0.7.1`; shared OOXML preflight dependency.
- Standard-library `csv`; extractor `python-csv`, version `1.0.0`, format `csv`.

No pandas, LibreOffice, Office automation, legacy DOC/XLS parser, converter, dynamic plugin loader,
or runtime dependency download was introduced. Organizational approval and release-image scanning
of these exact pins and their transitive dependencies remain pending.

## Shared OOXML Controls

DOCX and XLSX use the Step 4 workspace shape: an exact `input.<suffix>` regular file under a UUID
child of the configured processing root. Symlinks, wrong names, paths outside the root, empty Office
inputs, oversized inputs, and unsafe file types fail closed. SHA-256 is calculated through bounded
streaming and no path is returned in an extraction result.

Before a format library opens an OOXML package, the shared preflight validates ZIP entry names,
duplicates, traversal, absolute paths, special files, encryption flags, entry count, compressed and
expanded aggregate bytes, per-entry bytes, and expansion ratio. It rejects VBA, ActiveX, embedded
objects, executable parts, macro content types, malformed packages, and OLE encrypted containers.
Every XML and relationship part is parsed with DTD, entity, and external-entity processing disabled.
Worksheet cell references, total cells, merged ranges, and worksheet count are bounded before
openpyxl iteration.

Errors use existing fixed extraction codes and messages. Parser, XML, ZIP, Unicode, filesystem,
document-content, filename, path, key, endpoint, and relationship details are not returned or used
as metric labels. Unexpected failures log only the exception type category.

## DOCX Contract

The DOCX extractor iterates body XML children so paragraphs and tables retain their actual order.
It records bounded heading paths, list levels, paragraph/list/heading types, deterministic table-row
text, table order, header-row metadata, and extractor identity. Repeated merged-cell objects in a row
are emitted once. Headers and footers are excluded from canonical body blocks and produce a stable
warning when package parts exist. Images and embedded content are ignored; image-only or empty body
content fails with `DOCUMENT_NO_EXTRACTABLE_CONTENT`. External relationships are retained only as
inert package data and are never fetched.

## XLSX Contract

The XLSX extractor opens workbooks with `read_only=True`, `data_only=True`, and `keep_links=False`.
It processes visible worksheets only, warns when hidden sheets are skipped, and always closes the
workbook in `finally`. Output preserves sheet name, one-based row range, stable cell order, bounded
canonical scalar formatting, and the first populated row after each blank boundary as a region
header. Incorrect declared dimensions are reset only after archive XML proves actual cell references
remain bounded.

Formulas are never evaluated. Only cached values exposed by data-only loading can enter canonical
rows. Formula cells without cached values produce a stable warning; formula expressions are not
substituted as computed content. External links are disabled and no networking module is imported.

## CSV Contract

CSV input is streamed as strict UTF-8 with an optional initial BOM. Delimiter selection compares
only comma, semicolon, tab, and pipe using bounded deterministic parsing, including quoted delimiters
and embedded newlines. Empty or invalid input fails with stable codes. Rows retain one-based logical
record positions. Blank headers receive deterministic `column_N` labels and duplicate headers get
stable numeric suffixes with bounded warning codes. Formula-like prefixes remain canonical text and
are never evaluated or neutralized during ingestion.

The implementation bounds input bytes, fields, columns, logical records, blocks, per-block text,
and aggregate extracted characters. The process-global standard-library CSV field limit is changed
only while holding an in-process lock and is restored on every exit.

## Limits, Registry, Readiness, And Metrics

New typed limits cover archive entries, compressed bytes, expanded bytes, individual entries,
expansion ratio, spreadsheet columns/cells, merged ranges, CSV columns, and CSV field characters.
Cross-field validation prevents an archive entry from exceeding the aggregate expansion bound and
prevents CSV column limits from exceeding spreadsheet column limits.

Release registry construction remains explicit and static. Office/CSV modules are imported only
inside release-registry construction, not by API readiness. There is no importlib, entry-point or
filesystem discovery, eval, exec, shell execution, or parser selection from content. Worker registry
readiness now passes only with the real PDF, DOCX, XLSX, and CSV registrations.

Metrics expose only allowlisted format and outcome labels plus numeric duration, block, row, and
worksheet distributions. They do not label document text, formulas, sheet names, headers, hashes,
paths, filenames, identifiers, endpoints, or exception messages.

Legacy `.doc` and `.xls` are absent from project-document and reference-template upload allowlists.
Historical display classification was not changed.

## Verification Evidence

Focused Step 7 extraction, packaging, registry, readiness, architecture, and metrics selection:

```text
67 passed, 1 warning in 4.85s
```

Step 4 through Step 6 regression selection:

```text
179 passed, 2 skipped, 1 warning in 4.94s
```

Complete backend suite after the final implementation:

```text
386 passed, 4 skipped, 1 warning in 51.40s
```

The skips are existing Windows symlink/PostgreSQL integration gates. The warning is the existing
Starlette TestClient deprecation warning. One earlier full-suite attempt was externally paused for
about 39 minutes, causing three clock-sensitive timeout/SSO cases to age past their assertions; the
three cases passed immediately when rerun, and the uninterrupted final suite passed completely.

Quality and dependency consistency:

```text
python -m ruff check .
All checks passed!

python -m ruff format --check <18 changed Python files>
18 files already formatted

python -m pip check
No broken requirements found.

git diff --check
Exit 0; existing line-ending notices only.
```

Frontend allowlist verification:

```text
npm run build
Build passed.

npm run lint
Lint passed.

npx playwright test tests/create-wbs.spec.ts -g "legacy document formats"
1 passed.
```

## Vulnerability Result

`pip-audit` ran against the installed environment and reported 22 advisory records affecting four
pre-existing packages: `certifi 2026.7.22`, `cryptography 46.0.7`, `pip 25.0.1`, and development-only
`pytest 8.4.2`. It reported no finding for python-docx, openpyxl, defusedxml, or their installed
dependencies. The overall vulnerability gate therefore remains failed. Updating the unrelated
authentication/tooling constraints is outside Step 7 and requires a separate reviewed change.

## External Release Gates

- Obtain organizational approval for the exact parser and transitive dependency versions.
- Resolve or formally disposition the current dependency-audit findings.
- Build and scan the release worker image; Docker was not installed in this environment.
- Run the complete abuse suite inside the non-root worker with a read-only root filesystem.
- Prove network isolation for representative DOCX relationships and XLSX external-link packages in
  the deployed worker environment.
- Measure representative DOCX/XLSX/CSV throughput, peak memory, temporary disk use, and configured
  maximum behavior.
- Verify container CPU, memory, filesystem, task timeout, and cancellation controls.
- Inspect release logs, metrics, and traces for content and infrastructure disclosure.
- Complete remaining execution-plan steps before enabling document ingestion.

## Residual Risks

- Office parsers remain in-process blocking libraries; later worker task/process isolation must
  enforce hard execution time and memory limits.
- OOXML preflight materializes one XML part at a time up to the configured entry bound; release
  container memory limits remain mandatory.
- Parser correctness and performance are repository-tested with synthetic fixtures, not customer
  documents or a release worker image.
- XLSX cached-formula availability depends on the source producer; missing cached values are warned
  and omitted rather than evaluated.
- Real release-network denial and external-link behavior still require container-level evidence.
