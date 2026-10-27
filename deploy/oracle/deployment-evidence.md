# Background services deployment: 2026-10-26

Deployment location: `/home/developer/wbs-services/deploy/oracle`.
Observed host: Ubuntu 24.04 ARM64, 1 CPU, approximately 6 GB RAM.

All four long-running services reported healthy:

| Service | Deployment |
| --- | --- |
| Redis | Official 7.4 Alpine image, digest pinned in Compose; password protected; persistent AOF |
| Celery worker | Application backend image; Celery 5.6.3; concurrency 1 |
| Celery Beat | One scheduler with persistent schedule state |
| ClamAV | Ubuntu ARM64 packages; engine 1.5.4; signature database 28165 |

Verified on the running VM:

- Authenticated Redis PING succeeds; unauthenticated PING returns NOAUTH.
- Runtime Neon connection succeeds using a read-only transaction.
- Worker S3 credentials successfully pass the application's read-only bucket check.
- Application ClamAV client accepts a clean file and detects the harmless EICAR test signature.
- A harmless registered Celery task completes through broker, worker, and result backend.
- Beat automatically publishes its first 60-second tasks and the worker completes them.
- A read-only administrative preflight found zero deleting documents and zero recoverable deletion dispatches.
- Initial deployment had no host port bindings. All four services use `restart: unless-stopped`.
- Runtime credentials and Redis password files have mode 0600 in an owner-only deployment directory.
- Idle container memory usage was approximately 1.2 GB total; this is not an OCR/embedding load benchmark.

Runtime database and S3 credentials were transferred with explicit user approval.
Migration-owner credentials were excluded. Temporary local credential copies and
transfer archives were removed after deployment. No schema migration was run.

The API/frontend and OCR/embedding runtime are not deployed in this step. Local
`backend/.env` was initially unchanged; the local-access addendum below records its later connection.
Document ingestion, retention, orphan cleanup, and reconciliation repair modes
remain disabled. Scheduled deletion recovery follows the existing application
schedule and may act on future deletion requests.

## Local Windows access: 2026-10-26

- Redis publishes only `127.0.0.1:6379` on the VM; ClamAV publishes only `127.0.0.1:3310`.
- A native OpenSSH tunnel forwards Windows `127.0.0.1:16379` and `127.0.0.1:13310` to those VM loopback ports.
- Local `backend/.env` now contains the authenticated tunneled Redis URL and ClamAV host/port.
- Local Redis authentication, a clean-file ClamAV scan, and a harmless remote Celery task round trip all passed.
- `TASKS_EAGER=true` and `DOCUMENT_INGESTION_ENABLED=false` remain unchanged locally.
- No public Redis/ClamAV ports or OCI firewall openings were added.
- PowerShell script execution is disabled on this PC. The connection uses native `ssh`, with no execution-policy change.

## Worker image upgrade: 2026-10-26

- Built the native ARM64 `wbs-ingestion-worker:local` image using the existing `ocr-worker` target.
- Installed OCRmyPDF 16.7.0+dfsg1, Tesseract 5.5.0 with English data, Ghostscript 10.05.1, and QPDF 12.2.0.
- Installed constrained FastEmbed 0.9.0, ONNX Runtime 1.31.0, and tokenizers 0.22.2.
- Packaged the SHA256-verified BGE model/tokenizer from the committed manifest.
- Passed model, tokenizer, embedding, OCR tool/version/language, and extractor registry checks offline.
- Passed native text-PDF extraction -> three blocks -> one canonical chunk -> a 384-dimensional embedding, with networking disabled and a read-only container root filesystem.
- Actual image-only PDF OCR returned `DOCUMENT_PARSER_RESOURCE_EXHAUSTED`; that path was deferred at the user's explicit request.
- Switched only the Celery worker to the new image after confirming no active tasks.
- Worker has a 2304 MB memory cap, one embedding CPU thread, a private processing volume, and bounded `/tmp`.
- Scheduler retains its base backend image; Redis and ClamAV retain their existing deployment.
- Runtime versions/model pins are in generated `worker-runtime.env`, separate from credential-bearing `worker.env`.
- Ingestion, retention, orphan cleanup, and reconciliation repair flags remain disabled. API configuration restrictions are still outstanding.

## Local native text-PDF ingestion enabled: 2026-10-26

This addendum supersedes the earlier disabled-ingestion snapshots above.

- Added the explicit `DOCUMENT_INGESTION_LOCAL_DEVELOPMENT` opt-in, allowed only
  in development. Default development and all production guards remain in place.
- Local API uses authenticated Redis through the SSH tunnel, S3 uploads, and the
  restricted Neon runtime role. Its model/tokenizer pins match the worker image.
- Worker holds the non-secret migration role name instead of migration credentials.
  Runtime-role checks confirm no superuser, RLS-bypass, or database-owner membership.
- Rebuilt worker image `4f107874f66c` and scheduler image `a0c4d2b13fda`; both
  services are healthy with ingestion enabled and non-eager task execution.
- Authenticated Redis, rejection of unauthenticated clients, read-only Neon/S3
  connectivity checks, ClamAV clean-file/EICAR detection, and worker ping passed.
- The initial API submission returned 503 after the SSH tunnel disconnected.
  Reconnected the tunnel and reused the same uploaded verification PDF.
- Native PDF completed on the first worker attempt through scanning, extraction,
  chunking, embedding, persistence, and activation. Direct tenant-scoped database
  verification found one active chunk with a 384-dimensional vector.
- Repeating ingestion resolved to the same completed job without a second run.
- Verification project: `527e9600-cf1c-486e-841b-08e9ff2d1291`.
- Verification document: `fc5773c4-468c-4af7-acf7-45d143267fd4`.
- Job: `20525778-6f11-4c61-97b3-d1add7fb7149`.
- Active processing run: `2b460160-1449-49f1-9292-39a08025fa8c`.
- 101 targeted configuration/API/dispatch/orchestration/readiness tests passed.
  Ruff and `git diff --check` passed for the changed code.
- Public Redis/ClamAV ports remain closed; retention, orphan cleanup, and
  reconciliation repairs remain disabled. Scanned/image-only PDF OCR remains
  unverified and outside the requested native text-PDF flow.

The synthetic verification project/document are retained for inspection in the UI.
The temporary local API ran on port 8001; normal local startup uses port 8000.
