# Step 2: Verify and Complete PDF Upload Support

## Step Status

Repository implementation complete on 2026-10-24. Release-environment Neon Object Storage smoke
verification remains pending, so this step is not yet externally release-verified.

## Objective

Make PDF upload reliable and release-ready before extraction work begins. The current code already
advertises and accepts `.pdf`; this step verifies the complete path with genuine files, corrects MIME
handling, establishes stable upload errors, and removes formats that will not be fully processed in
the initial release.

## Execution Context

- `CreateWbsScreen.tsx` includes `.pdf` in `ACCEPTED_PROJECT_EXTENSIONS`.
- The FastAPI document route accepts `.pdf` with `application/pdf`.
- Storage validation checks the `%PDF-` signature but does not structurally parse the PDF.
- Existing tests use minimal bytes beginning with `%PDF-`; they are not proof that a genuine PDF can
  traverse browser, API, S3, database, and later parser boundaries.
- Browser or operating-system MIME detection can report a valid PDF as `application/octet-stream`.

## Prerequisites

- Step 1 complete.
- Rotated Neon Object Storage credentials injected into the release environment.
- A private non-production test tenant/project in the release environment.
- Synthetic, non-sensitive fixtures for text, scanned, encrypted, malformed, and oversized PDFs.

## Functional Requirements

- A permitted user can select or drag-and-drop a genuine PDF.
- Upload succeeds when extension, binary signature, and structure confirm a PDF.
- Browser MIME is advisory, not the sole source of trust.
- A file with a misleading `.pdf` suffix is rejected.
- Encrypted, malformed, empty, and oversized PDFs receive distinct stable error codes.
- Failed database persistence triggers retryable object cleanup without exposing the object key.
- Viewer roles and users outside the tenant/project remain unable to upload.

## Public Error Contract

Use stable codes with short safe messages, for example:

| Code | HTTP | Meaning |
| --- | --- | --- |
| `UNSUPPORTED_DOCUMENT_FORMAT` | 415 | Extension/format not allowed |
| `DOCUMENT_TYPE_MISMATCH` | 415 | Declared and detected types disagree |
| `DOCUMENT_EMPTY` | 400 | No uploaded bytes |
| `DOCUMENT_TOO_LARGE` | 413 | Configured size exceeded |
| `PDF_MALFORMED` | 422 | PDF structure cannot be read |
| `PDF_ENCRYPTED` | 422 | Password-protected PDFs are not supported |
| `OBJECT_STORAGE_UNAVAILABLE` | 503 | Retryable storage failure |

Keep compatibility with the API's existing error shape or introduce one reviewed common error schema.

## Implementation Tasks

1. Add genuine PDF fixtures produced by a trusted test generator or checked-in binary fixture policy.
2. Add UI tests for file picker and drag-and-drop selection.
3. Capture actual API error details in the upload UI.
4. Keep extension allowlisting and signature checks.
5. Permit `application/octet-stream` only for an allowlisted extension that passes server-side
   signature and structural validation.
6. Use `pypdf` structural opening after download in the processing path; do not attempt expensive
   full extraction during the request.
7. Add safe detection of encryption and gross structural corruption.
8. Preserve current upload size enforcement while reading in bounded chunks.
9. Keep the object key generated from tenant, project, category, and UUID only.
10. Remove `.doc` and `.xls` from project format lists unless their conversion step is approved.
11. Align UI hint text, `accept`, backend allowlists, schemas, tests, and documentation.
12. Ensure PDF files stored in Neon use the intended content type and private access controls.

## Files Expected to Change

- `WBS_UI/src/views/CreateWbsScreen.tsx`
- relevant React service/error handling files
- `backend/app/api/routes/documents.py`
- `backend/app/services/storage.py`
- error schema/module if introduced
- `backend/tests/test_workflow.py`
- `backend/tests/test_object_storage.py`
- Playwright upload tests and fixtures

## Test Matrix

Upload success:

- real text PDF reported as `application/pdf`;
- real text PDF reported as `application/octet-stream`;
- scanned but structurally valid PDF;
- filename containing spaces and multiple dots;
- maximum permitted size boundary.

Upload rejection:

- plain text renamed to `.pdf`;
- truncated PDF;
- encrypted PDF;
- empty PDF upload;
- file one byte above the limit;
- disallowed `.doc` and `.xls` after release-list correction;
- mismatched Office/PDF payload;
- user without upload permission;
- document upload to a project in another tenant.

Failure handling:

- S3 timeout;
- database commit failure after successful object upload;
- cleanup failure after database failure;
- aborted browser request;
- duplicate button activation while an upload is active.

## Security Checklist

- [x] Client MIME is never trusted by itself.
- [x] Original filename cannot influence storage path.
- [x] Upload remains private and tenant/project keyed.
- [x] File and request-body limits exist at edge and application layers.
- [x] Authorization occurs before storage calls.
- [x] Errors do not reveal object keys, bucket names, or provider details.
- [x] Spoofed, encrypted, and malformed PDFs are rejected safely.

## Observability

Record safe counters for accepted and rejected uploads by detected format and error code. Log opaque
tenant, project, document, and request IDs, but never log file contents, permanent object URLs, or
credentials.

## Verification

Run backend workflow/object-storage tests and the browser upload test. Perform one release-environment
smoke upload and confirm the object exists under the generated tenant/project prefix and the database
record contains matching safe metadata.

## Rollback

Disable new document upload or PDF advertisement if validation regresses. Do not loosen server-side
format checks to restore availability. Uploaded originals remain private and may be reprocessed after
the correction.

## Exit Criteria

- [x] Genuine text and scanned PDFs upload through picker and drag-and-drop in repository tests.
- [x] Generic MIME succeeds only after trusted server-side validation.
- [x] Spoofed, malformed, encrypted, empty, and oversized PDFs fail with stable errors.
- [x] UI and backend advertise the same release formats.
- [x] Authorization and cleanup failure tests pass.
- [ ] Release-environment storage smoke evidence is recorded.

## Handoff to Step 3 and Step 4

Provide the final supported-format registry, error codes, upload-size rules, document metadata, and
private storage-key contract. Step 3 uses the document identity in vector tables; Step 4 uses the
storage contract for secure download.

