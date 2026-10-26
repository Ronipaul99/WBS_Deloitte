# Step 2 Implementation Evidence

## Status

Repository implementation completed on 2026-10-24. The approved non-production Neon Object Storage
smoke upload and private-bucket verification remain pending. Step 2 is therefore repository-complete
but not externally release-verified.

## Scope Delivered

- Added lightweight `pypdf` structure and encryption checks without extracting text or rendering
  pages.
- Accepted `application/octet-stream` for `.pdf` only after extension, signature, and structural
  validation succeed.
- Normalized stored PDF content type to `application/pdf`.
- Removed legacy DOC and XLS from project-document upload lists.
- Added stable coded upload errors, controlled upload metrics, and safe UI error mapping.
- Added bounded object cleanup after database persistence failure.
- Added genuine synthetic text, image-only, encrypted, malformed, truncated, and size-boundary PDF
  coverage.
- Added picker, drag-and-drop, duplicate submission, network abort, safe error, and optional-template
  browser coverage.

No text extraction, OCR processing, malware scanning, ingestion worker, chunking, vector storage,
embedding, summary, LLM, or agentic implementation was added.

## Changed Files

- `backend/pyproject.toml`
- `backend/app/core/upload_errors.py`
- `backend/app/core/observability.py`
- `backend/app/api/routes/documents.py`
- `backend/app/services/storage.py`
- `backend/README.md`
- `backend/tests/pdf_fixtures.py`
- `backend/tests/test_pdf_upload.py`
- `backend/tests/test_object_storage.py`
- `backend/tests/test_authorization.py`
- `backend/tests/test_workflow.py`
- `WBS_UI/src/services/apiClient.ts`
- `WBS_UI/src/views/CreateWbsScreen.tsx`
- `WBS_UI/tests/pdf-fixtures.ts`
- `WBS_UI/tests/create-wbs.spec.ts`
- `WBS_UI/tests/workflow-mocks.ts`
- `WBS_UI/tests/fullstack/authorization-workflow.spec.ts`
- `docs/document-ingestion-vector-storage-steps/step-02-pdf-upload-support.md`
- `docs/document-ingestion-vector-storage-steps/step-02-artifacts/implementation-evidence.md`

`backend/.env` contents were not inspected, printed, modified, or included in evidence. Existing unrelated working-tree edits,
including the in-progress exact-WBS retrieval changes, were preserved.

## Supported Formats

Project documents:

| Extension | Accepted declared MIME types | Server validation |
| --- | --- | --- |
| `.pdf` | `application/pdf`, `application/octet-stream` | PDF signature plus strict `pypdf` structure/encryption check |
| `.docx` | Open XML Word MIME | ZIP signature and expected Office entries |
| `.xlsx` | Open XML Excel MIME | ZIP signature and expected Office entries |
| `.csv` | Existing CSV MIME allowlist | UTF-8-compatible sample without NUL bytes |

Legacy `.doc` and `.xls` are rejected for project documents. The existing template registry remains
XLS, XLSX, CSV, and XML because template conversion was outside this PDF project-document step.

## Public Error Contract

All Step 2 upload errors use `{"detail":{"code":"...","message":"..."}}`.

| Code | HTTP | Safe meaning |
| --- | --- | --- |
| `DOCUMENT_EMPTY` | 400 | No uploaded bytes |
| `DOCUMENT_TOO_LARGE` | 413 | Configured file limit exceeded |
| `UNSUPPORTED_DOCUMENT_FORMAT` | 415 | Extension not in the project registry |
| `DOCUMENT_TYPE_MISMATCH` | 415 | Declared, extension, signature, or detected structure disagree |
| `PDF_MALFORMED` | 422 | PDF structure cannot be opened |
| `PDF_ENCRYPTED` | 422 | Password-protected PDF |
| `OBJECT_STORAGE_UNAVAILABLE` | 503 | Retryable storage failure |

Parser messages, provider diagnostics, bucket names, object keys, filesystem paths, credentials, and
private endpoints are not returned. The UI maps known codes to fixed messages and uses a generic
fallback for unknown responses.

## Limits And Validation

- Application file limit: `MAX_UPLOAD_BYTES`, currently 25 MiB by default.
- Request-body limit: `MAX_REQUEST_BODY_BYTES`, currently 26 MiB by default.
- Files are measured in bounded 1 MiB chunks before validation or upload.
- Exact file-limit and one-byte-over-limit behavior is tested.
- `PdfReader(..., strict=True)` checks the server-controlled upload stream, encryption state, and at
  least one readable page. It does not extract text, render content, perform OCR, or load an AI model.
- Text and image-only fixtures are generated synthetically; no customer document is present.

## Storage And Authorization Controls

- Keys remain `tenants/{tenant}/projects/{project}/documents/{uuid}.{extension}`.
- Original filenames remain metadata and cannot influence object keys.
- PDF uploads are stored with `ContentType=application/pdf`, including browser uploads declared as
  `application/octet-stream`.
- No public ACL or permanent object URL was introduced.
- Tenant/project and upload-permission checks complete before `storage.save` is called.
- Database commit failure rolls back and performs at most two cleanup calls. Cleanup failure is
  logged by fixed category without the object key or provider exception.
- Metrics use controlled outcome, detected-format, and error-code label sets only.

## Verification Results

Backend:

```text
.\.venv\Scripts\python.exe -m pytest tests/test_pdf_upload.py tests/test_object_storage.py tests/test_workflow.py tests/test_authorization.py
33 passed, 1 existing Starlette deprecation warning

.\.venv\Scripts\python.exe -m pytest
161 passed, 1 existing Starlette deprecation warning

.\.venv\Scripts\python.exe -m ruff check <changed Step 2 Python files>
All checks passed

.\.venv\Scripts\python.exe -m ruff format --check <changed Step 2 Python files>
9 files already formatted

.\.venv\Scripts\python.exe -m pip check
No broken requirements found
```

Frontend:

```text
npm.cmd run build
Passed: TypeScript and Vite production build

npm.cmd run lint
Passed: ESLint

npx.cmd playwright test tests/create-wbs.spec.ts
6 passed

npx.cmd playwright test
42 passed

npx.cmd playwright test --config playwright.fullstack.config.ts --list
15 live full-stack tests collected with the required disposable test manifest; collection only
```

Repository:

```text
git diff --check
Passed; Git emitted line-ending conversion warnings only.

Step 2 dependency scan
No FastEmbed, pgvector, vector model, or later-step dependency was introduced.
```

## External Release Gates Pending

- Use rotated credentials and an approved non-production tenant/project to upload genuine text and
  image-only PDFs to Neon Object Storage.
- Confirm a valid PDF declared as `application/octet-stream` is normalized and stored successfully.
- Confirm the object exists under the generated tenant/project prefix and remains private.
- Confirm the database record matches safe filename, size, and `application/pdf` metadata.
- Exercise S3 timeout and cleanup alerts in the deployed environment without disclosing provider
  details.

No mocked or local repository test is presented as evidence for these external gates.

## Residual Risks

- Structural opening is not content extraction, malware analysis, OCR, or protection from every
  pathological PDF. Those controls belong to later approved steps.
- Cleanup is bounded and best-effort; this step deliberately does not add a durable cleanup job or
  persistence schema.
- Private bucket policy and real Neon behavior require the pending release smoke verification.
- Full-stack release tests will need the approved synthetic PDF fixtures once run against the actual
  release environment.
