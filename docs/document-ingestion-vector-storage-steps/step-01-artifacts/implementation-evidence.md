# Step 1 Implementation Evidence

## Status

Repository implementation completed on 2026-10-24. External release-service, container-image, and
deployment-startup verification remains pending. `DOCUMENT_INGESTION_ENABLED` must remain `false`
until those gates and later ingestion steps are complete.

## Scope Delivered

- Added typed, bounded ingestion settings and cross-field release validation.
- Added fail-closed production rejection for eager tasks.
- Required production Neon pooled runtime and direct migration URLs with TLS through the existing
  production validation, private S3-compatible storage configuration, a non-local Redis URL, the
  approved FastEmbed provider/model/dimensions, a compatible chunk window, OCR, ClamAV, and an
  absolute worker model path.
- Added an ingestion-disabled dependency returning a stable `503` response without creating work.
- Split readiness so API readiness checks Redis dispatch only, while worker readiness additionally
  checks ClamAV and a readable packaged model directory.
- Added a worker preflight command that returns only safe dependency categories and does not import
  or load FastEmbed.
- Kept ingestion disabled by default with no local fallback.
- Added release-only example configuration and operator documentation without real credentials or
  endpoints.

No PDF changes, parser, OCR implementation, scanner pipeline, extractor, chunker, ingestion job,
database migration, pgvector table, FastEmbed package, model download, or React change was added.

## Changed Files

- `backend/app/core/config.py`
- `backend/app/services/readiness.py`
- `backend/app/api/routes/health.py`
- `backend/app/api/dependencies.py`
- `backend/app/cli.py`
- `backend/.env.example`
- `backend/README.md`
- `backend/tests/conftest.py`
- `backend/tests/test_database_config.py`
- `backend/tests/test_health.py`
- `backend/tests/test_ingestion_readiness.py`
- `docs/document-ingestion-vector-storage-steps/step-01-release-configuration-gate.md`
- `docs/document-ingestion-vector-storage-steps/step-01-artifacts/implementation-evidence.md`

`backend/.env` was not changed or read into evidence. Existing unrelated working-tree changes were
left intact.

## Implemented Controls

| Control | Evidence |
| --- | --- |
| Fail closed when enabled | The settings validator rejects incomplete or unsafe enabled profiles in every environment; production adds Neon and TLS requirements. |
| Safe validation errors | Pydantic input values are hidden from error rendering and tests assert a Redis credential is absent. |
| Safe readiness output | Public health returns only `Service is not ready.`; logs and worker preflight use fixed dependency categories. |
| API/model separation | API readiness calls Redis only; a test makes any model-path inspection fail immediately. |
| Worker release preflight | `python -m app.cli check-ingestion-worker-readiness` checks Redis, ClamAV `PING`, and a readable file below the absolute model directory. |
| No runtime model download | No FastEmbed import, package, loader, or download behavior was added. |
| Disabled local path | Ingestion defaults to disabled, cannot be enabled in development, and enabled validation rejects SQLite, local storage, eager tasks, and local Redis. |
| Browser secret boundary | A repository scan found no `VITE_*` variable containing database, Redis, scanner, embedding, storage, AWS, or secret configuration. |

## Verification Results

From `backend`:

```text
.\.venv\Scripts\python.exe -m pytest tests/test_database_config.py tests/test_ingestion_readiness.py tests/test_health.py
61 passed, 1 existing Starlette deprecation warning

.\.venv\Scripts\python.exe -m pytest
144 passed, 1 existing Starlette deprecation warning

.\.venv\Scripts\python.exe -m ruff check app/core/config.py app/services/readiness.py app/api/routes/health.py app/api/dependencies.py app/cli.py tests/conftest.py tests/test_database_config.py tests/test_health.py tests/test_ingestion_readiness.py
All checks passed

.\.venv\Scripts\python.exe -m ruff format --check app/core/config.py app/services/readiness.py app/api/routes/health.py app/api/dependencies.py app/cli.py tests/conftest.py tests/test_database_config.py tests/test_health.py tests/test_ingestion_readiness.py
9 files already formatted
```

From the repository root:

```text
git diff --check
Passed; Git emitted only line-ending conversion warnings for existing working-tree files.

rg -n "VITE_[A-Z0-9_]*(DATABASE|REDIS|CLAMAV|EMBEDDING|AWS_|STORAGE|SECRET)[A-Z0-9_]*\\s*=" . -g "!backend/.venv/**" -g "!WBS_UI/node_modules/**" -g "!.git/**"
No matches
```

## External Release Gates Pending

- Validate the real pooled and direct Neon connections, TLS, migration head, and distinct release
  credentials in the release environment.
- Validate the private object-storage bucket and rotated release credential.
- Validate API and worker connectivity to the real Redis service.
- Validate worker connectivity to the real ClamAV service and its expected `PING` response.
- Build the release images and confirm the API image contains no model files while the worker image
  contains `/opt/wbs-models/bge-small-en-v1.5` as a read-only directory.
- Run `python -m app.cli check-production-config` and
  `python -m app.cli check-ingestion-worker-readiness` in the release images.
- Start API and worker images with deliberately invalid settings and retain evidence that each
  process fails before accepting work.

No external gate is marked complete by repository tests or mocks.

## Residual Risks

- Worker readiness proves that the configured directory contains a readable file, not that model
  artifacts are complete or cryptographically verified. FastEmbed loading belongs to Step 9.
- Redis and ClamAV failure behavior is repository-tested with mocks; real network, TLS, DNS, and
  authentication behavior remains an external release check.
- The worker preflight command must be enforced by the release entrypoint or deployment workflow
  before Celery starts.
- Ingestion is intentionally unusable until the later upload, extraction, storage, and processing
  steps are implemented and verified.
