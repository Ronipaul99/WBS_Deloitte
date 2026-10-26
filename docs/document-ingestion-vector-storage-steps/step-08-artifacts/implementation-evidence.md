# Step 8 Implementation Evidence

## Status

The Step 8 repository implementation is complete as of 2026-10-25. Normalization and chunking are
not release-worker verified. The approved immutable `BAAI/bge-small-en-v1.5` tokenizer artifact and
revision were unavailable, Docker is not installed in this environment, performance/resource
tests were not run in a release worker, and the existing dependency vulnerability gate remains
failed. `DOCUMENT_INGESTION_ENABLED` must remain false.

## Changed Files

- `backend/app/services/ingestion/normalization.py`
- `backend/app/services/ingestion/tokenizer.py`
- `backend/app/services/ingestion/chunk_types.py`
- `backend/app/services/ingestion/chunking.py`
- `backend/app/services/ingestion/errors.py`
- `backend/app/core/config.py`
- `backend/app/core/observability.py`
- `backend/app/services/readiness.py`
- `backend/app/cli.py`
- `backend/pyproject.toml`
- `backend/Dockerfile`
- `backend/.env.example`
- `backend/README.md`
- `backend/tests/chunking_fixtures.py`
- `backend/tests/test_document_normalization.py`
- `backend/tests/test_document_chunking.py`
- `backend/tests/test_chunking_tokenizer.py`
- Narrow additions to existing configuration, readiness, observability, and architecture tests
- The Step 8 execution document and this evidence file

No extractor behavior, FastAPI route, React file, database model, Alembic migration, ingestion job,
FastEmbed runtime, embedding generation, vector persistence/search, summary, RAG, LLM, or agentic
workflow was added by Step 8.

## Contract And Versions

- Chunker: `deterministic-source-chunker`, version `1.0.0`.
- Model/tokenizer identity: `BAAI/bge-small-en-v1.5`.
- Worker-only tokenizer runtime: `tokenizers==0.22.2`.
- Tokenizer artifact: exact local `tokenizer.json` plus `tokenizer-revision.txt`.
- Artifact controls: configured immutable revision, lowercase SHA-256, constant-time digest and
  revision comparison, regular readable files, no symlinks, bounded artifact/revision size, and an
  exact model-directory boundary.
- Token contract: target 400, overlap 50, maximum canonical content 480, formatting/special-token
  headroom 32, model sequence length 512.
- Collection bounds: configurable maximum chunks and source references in addition to the existing
  extraction character, heading, warning, and metadata bounds.

The worker pin was changed from an initially tested `tokenizers==0.23.3` candidate to `0.22.2`.
Version 0.23.3 pulled an `httpx2` dependency that changed existing Starlette cookie behavior and
failed two authentication regressions. Version 0.22.2 retains the existing `httpx<1` dependency
line; after the correction, the full backend suite passed. Organizational approval of the exact
pin and its transitive dependencies remains pending.

## Normalization

Normalization is a pure, idempotent operation. It canonicalizes line endings, horizontal Unicode
whitespace, unsafe control characters, repeated blank lines, and spaces around the stable table
separator. It preserves Unicode content, identifiers, numbered and bulleted lists, punctuation,
dates, currencies, units, quantities, percentages, negation, exclusions, assumptions, constraints,
risks, table cell positions, headings, and source locations. It performs no semantic rewrite,
translation, spelling correction, summarization, instruction interpretation, or external call.

## Chunking And Provenance

The chunker consumes only a validated `ExtractionResult` and an injected tokenizer/policy. It
normalizes blocks independently, records empty blocks, groups compatible source blocks, splits
oversized text at deterministic structural/character boundaries, and preserves table values with
column labels. Worksheet/table headers are repeated as context without changing primary row
ranges. Compatible text chunks can receive bounded overlap; overlap and header references are
separate from primary coverage.

Every chunk is immutable and contains its zero-based ordinal, canonical content, exact model token
count, deterministic SHA-256, exact source references and roles, primary/overlap/header ordinals,
page set, worksheet and primary row range, heading path, extraction methods, and stable warnings.
Every retained source block must have primary coverage. Chunks cannot mix worksheets. DOCX/CSV do
not invent unsupported locations.

Hashing uses canonical UTF-8 JSON with sorted keys and compact separators under domain
`wbs-canonical-chunk-v1`. The payload includes chunker/tokenizer identity, source content hash,
format, canonical content, heading path, and ordered source references. It excludes random IDs,
timestamps, tenant/project identifiers, filesystem paths, and environment-dependent values.
Hashes are deterministic identifiers only and do not replace authorization or integrity controls.

## Errors, Readiness, And Observability

Step 8 adds fixed safe codes for tokenizer unavailability/artifact failure, normalization failure,
chunk limits, coverage failure, and unexpected chunking failure. Job mappings contain only the
stable code, retryability, and fixed message. Unexpected failures log only an exception type
category.

API readiness does not import the tokenizer package, inspect worker artifacts, tokenize content, or
construct a chunker. Worker readiness lazily loads the local adapter, verifies model identity,
revision, sequence length, artifact integrity, and a bounded synthetic self-check, and returns only
`tokenizer_runtime` on failure. It does not load FastEmbed or an embedding model.

Metrics use allowlisted format, outcome, stable error, and event labels. Numeric observations cover
duration, input blocks, chunks, tokens, splits, overlap, and empty blocks. Content, hashes, headings,
sheet names, identifiers, paths, endpoints, tokenizer output, and exception text are not labels.

## Verification Evidence

Focused Step 8 configuration, normalization, chunking, tokenizer, readiness, observability, and
architecture selection:

```text
94 passed, 1 warning in 2.09s
```

Step 4 through Step 7 regression selection:

```text
209 passed, 2 skipped, 1 warning in 5.04s
```

Complete backend suite after restoring the compatible tokenizer dependency graph:

```text
410 passed, 4 skipped, 1 warning in 38.90s
```

The skips are existing Windows symlink/PostgreSQL integration gates. The warning is the existing
Starlette TestClient deprecation warning.

Quality and dependency consistency:

```text
python -m ruff check .
All checks passed!

python -m ruff format --check <17 changed Python files>
17 files already formatted

python -m pip check
No broken requirements found.

git diff --check
Exit 0; existing line-ending notices only.
```

Repository tests verified normalization idempotence, meaning preservation, table separators,
immutable output, target/maximum boundaries, deterministic serialization/hashes, source coverage,
heading boundaries, PDF/DOCX/XLSX/CSV provenance, worksheet isolation, primary versus overlap/header
roles, row-range separation, safe failures, metric label bounding, local artifact integrity, and
API/worker readiness separation. A synthetic local `tokenizer.json` proved the real adapter's local
load/digest/revision path. It was not the approved BGE production artifact.

## Vulnerability Result

`pip-audit` completed using a temporary writable cache. It reported 22 advisory records affecting
four pre-existing packages: `certifi 2026.7.22`, `cryptography 46.0.7`, `pip 25.0.1`, and
development-only `pytest 8.4.2`. It reported no advisory for `tokenizers 0.22.2` or its installed
dependencies. The overall vulnerability gate remains failed. Resolving or formally accepting the
existing findings is outside Step 8.

## External Release Gates

- Approve the exact tokenizer runtime and transitive dependency versions.
- Obtain and record the immutable approved BGE tokenizer revision and artifact SHA-256.
- Package the real tokenizer artifacts read-only in the worker image only.
- Build and inspect API and worker targets; Docker was unavailable in this environment.
- Prove the API image contains no tokenizer runtime or model artifacts.
- Run the actual BGE golden fixtures repeatedly across fresh worker processes with networking
  disabled and compare byte-for-byte serialized output.
- Verify Step 9 will use the identical tokenizer/special-token contract.
- Measure representative and configured-maximum throughput, peak memory, and chunk-count growth.
- Inspect deployed logs, metrics, traces, and readiness for sensitive-data disclosure.
- Resolve or formally disposition the dependency audit findings.

## Residual Risks And Step 9 Handoff

- Repository token-boundary tests use a deterministic fake tokenizer; the adapter load path uses a
  synthetic local tokenizer. Neither proves parity with the approved BGE artifact.
- Character-bound fallback splitting preserves content deterministically but representative
  language/table quality still needs review with the real tokenizer and release fixtures.
- The chunker is synchronous. Later task/process orchestration must enforce execution time and
  memory limits outside FastAPI request handling.
- Tenant/project/document IDs intentionally do not enter canonical chunks or hashes. Step 10 must
  attach and database-enforce the already-authorized processing scope during persistence.
- Step 9 must embed only canonical chunk content, use this exact tokenizer contract, attach one
  384-dimensional vector per chunk, and must not mutate Step 8 content, order, hashes, or provenance.
