# Step 4 Implementation Evidence

## Status

Repository implementation completed on 2026-10-25. Private Neon Object Storage, the approved
ClamAV service, and the non-root Linux worker filesystem have not been exercised from this
workspace. Step 4 is repository-complete but not externally release-verified, and ingestion must
remain disabled until those release gates pass.

## Scope Delivered

- Extended the existing storage protocol with typed object metadata and bounded-download results.
- Added private S3 `HeadObject` inspection and fixed-size streaming through the existing thread-pool
  pattern.
- Added byte-count reconciliation and streaming SHA-256 calculation with constant-time trusted
  checksum comparison.
- Added an owner-only UUID temporary-workspace context with generated input names and guarded
  cleanup.
- Added a typed ClamAV scanner using bounded `INSTREAM` framing, response validation, and a
  content-free readiness `PING`.
- Added an internal persisted document/job boundary that yields a path only after scope, size,
  integrity, and clean-scan validation.
- Added stable retry and permanent error classifications plus low-cardinality metrics.
- Added focused clean, infected, unavailable, malformed, size, hash, traversal, failure,
  cancellation, timeout, concurrency, cleanup, readiness, and redaction coverage.

No document extraction, parser selection, OCR, tokenization, chunk generation, FastEmbed runtime,
model download, vector persistence, vector search, summary, LLM, RAG, agentic workflow, public
download endpoint, React change, database migration, queue producer, or worker orchestration was
implemented.

## Changed Files

- `backend/app/core/config.py`
- `backend/app/core/observability.py`
- `backend/app/services/storage.py`
- `backend/app/services/readiness.py`
- `backend/app/services/ingestion/__init__.py`
- `backend/app/services/ingestion/errors.py`
- `backend/app/services/ingestion/workspace.py`
- `backend/app/services/ingestion/scanning.py`
- `backend/app/services/ingestion/input_preparation.py`
- `backend/.env.example`
- `backend/README.md`
- `backend/tests/test_database_config.py`
- `backend/tests/test_ingestion_readiness.py`
- `backend/tests/test_secure_object_download.py`
- `backend/tests/test_ingestion_workspace.py`
- `backend/tests/test_malware_scanning.py`
- `backend/tests/test_document_input_preparation.py`
- `backend/tests/test_ingestion_observability.py`
- `docs/document-ingestion-vector-storage-steps/step-04-object-download-malware-scan.md`
- `docs/document-ingestion-vector-storage-steps/step-04-artifacts/implementation-evidence.md`

`backend/.env` was not inspected, printed, modified, or included in evidence. Existing Step 1,
Step 2, Step 3, authentication, workflow, and React working-tree changes were preserved.

## Storage Contract

`StoredObjectMetadata` contains only bounded content type, byte count, normalized SHA-256 when the
provider supplies one, and a sanitized entity tag. The entity tag is never treated as a content
hash. `DownloadResult` contains only the actual byte count and calculated lowercase SHA-256.

S3 inspection rejects missing, malformed, and oversized objects before download. Download reads in
fixed-size chunks, enforces the maximum again while streaming, uses an exclusive owner-only output
file, calculates SHA-256 during the write, reconciles the response byte count, closes the provider
body, and removes partial output on every failure. Provider errors are reduced to fixed categories
without returning keys, bucket names, URLs, credentials, or response details.

The local implementation supports the same bounded protocol for regression tests but remains
unavailable as a release ingestion backend through the existing configuration gate.

## Trusted Input Contract

`prepare_document_input` accepts ORM `Document` and `Job` records, not a public object key. It
requires an active persisted `DOCUMENT_INGESTION` job whose tenant, project, and requested document
match the project document. When a processing run is supplied, its document, job, tenant, and
project scope must also agree.

The persisted key must match the generated
`tenants/{tenant}/projects/{project}/documents/{uuid}.{suffix}` shape. The confirmed suffix and
persisted MIME type must be an approved PDF, DOCX, XLSX, or CSV combination. The original filename
never participates in a filesystem path.

The yielded `TrustedDocumentInput` contains only the controlled temporary path, confirmed suffix,
byte count, calculated SHA-256, and clean scan status. The context removes the path after the
consumer exits or raises.

## Temporary Workspace Controls

- The configured root must already exist, resolve to itself, be a non-root directory, belong to the
  worker account, and have no group or world permissions on POSIX.
- Every attempt receives a random UUID child with mode `0700` where supported.
- The input uses a fixed `input` basename and an allowlisted server-confirmed suffix.
- File creation is exclusive, uses mode `0600`, and uses `O_NOFOLLOW` where supported.
- Cleanup accepts only a UUID child whose resolved parent is the validated root.
- A replaced directory symlink is unlinked without following it.
- Success, download failure, scanner rejection, consumer failure, cancellation, and timeout paths
  execute cleanup. Cleanup errors contain no path or document information.

## Malware Scanner Contract

The ClamAV client sends the completed temporary file using the NUL-framed `INSTREAM` protocol. It
has bounded connection, overall scan, and response limits; bounds the file again; validates the
terminator and exact response form; and retains only a sanitized detection identifier. Clean,
infected, and unavailable are typed outcomes. Timeout, connection failure, malformed, truncated,
oversized, non-ASCII, error, and unknown responses are unavailable and fail closed.

Worker readiness sends only `PING` and accepts only `PONG`. API ingestion readiness continues to
check Redis without contacting ClamAV, opening worker files, or loading an embedding model.

## Stable Error Classification

| Code | Retryable | Security review |
| --- | --- | --- |
| `DOCUMENT_OBJECT_MISSING` | No | No |
| `OBJECT_STORAGE_UNAVAILABLE` | Yes | No |
| `DOCUMENT_INTEGRITY_FAILED` | No | Yes |
| `MALWARE_SCANNER_UNAVAILABLE` | Yes | No |
| `DOCUMENT_REJECTED_MALWARE` | No | Yes |
| `PROCESSING_STORAGE_UNAVAILABLE` | Yes | No |

Messages are fixed and do not include provider, socket, filesystem, document, tenant, path, or
scanner details.

## Observability Controls

Metrics record bounded download duration/outcome, successful byte counts, scanner duration/outcome,
and trusted/rejected input codes. Labels are restricted to fixed outcome and error-code allowlists.
Tenant, project, document, object-key, filename, hash, signature, path, endpoint, and exception
values are never labels. Logs contain only fixed operation categories and exception type names.

## Verification Results

Focused Step 4 and supporting configuration tests:

```text
.\.venv\Scripts\python.exe -m pytest tests\test_database_config.py tests\test_object_storage.py tests\test_secure_object_download.py tests\test_ingestion_workspace.py tests\test_malware_scanning.py tests\test_document_input_preparation.py tests\test_ingestion_observability.py tests\test_ingestion_readiness.py -q
108 passed, 1 skipped, 1 existing Starlette deprecation warning
```

The skipped test creates a directory symlink and requires Windows privileges unavailable in this
workspace. It is retained for the Linux worker test environment.

Complete backend suite:

```text
.\.venv\Scripts\python.exe -m pytest -q
218 passed, 3 skipped, 1 existing Starlette deprecation warning
```

Two additional skips are the Step 3 PostgreSQL/Neon tests requiring explicitly approved disposable
database credentials. No skipped test is presented as release evidence.

Quality and dependency checks:

```text
.\.venv\Scripts\python.exe -m ruff check <Step 4 Python files>
All checks passed

.\.venv\Scripts\python.exe -m ruff format --check <Step 4 Python files>
16 files already formatted

.\.venv\Scripts\python.exe -m pip check
No broken requirements found

git diff --check
Passed; Git emitted existing line-ending conversion warnings only
```

## External Release Gates Pending

- Provision the absolute temporary root in the Linux worker with the approved non-root owner and
  owner-only permissions.
- Confirm the ClamAV route is private and its `StreamMaxLength` supports `MAX_UPLOAD_BYTES`.
- Use approved synthetic data to inspect and stream a private object from an isolated Neon bucket.
- Confirm actual Neon size and checksum metadata behavior and the calculated known SHA-256.
- Confirm an actual clean scan and complete temporary cleanup in the worker runtime.
- Confirm the standard antivirus test signature is rejected, classified permanently, audited, and
  cleaned up by the deployed ClamAV service.
- Confirm scanner outage, timeout, and malformed-response simulations fail closed and are retryable.
- Confirm cancellation and worker timeout behavior under the deployed process supervisor.
- Inspect release logs, traces, metrics, and readiness output for sensitive-data absence.

No Neon, ClamAV, Linux-permission, private-network, or release-worker result is claimed from mocked
or Windows repository tests.

## Residual Risks

- Existing documents can have a null persisted content hash. Step 4 always calculates SHA-256, but
  an independent comparison occurs only when a trusted document or provider checksum is available.
- The real ClamAV daemon limits and S3-compatible streaming semantics require the pending release
  smoke test.
- The POSIX owner, permission, and symlink controls have not run in this Windows workspace.
- Abrupt process or node termination cannot execute a context-manager cleanup; release operations
  still need an approved stale-workspace reconciliation policy.
- This step exposes an internal preparation boundary only. Durable retries, job lifecycle updates,
  and task orchestration remain later-step work.
