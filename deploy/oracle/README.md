# Oracle background services

This Compose project runs Redis, the application's Celery worker, one Celery Beat
scheduler, and ClamAV on Ubuntu 24.04 ARM64. The API and frontend are not included.
The worker uses `wbs-ingestion-worker:local` with the packaged embedding model and
OCR executables. The scheduler retains the smaller base backend image. Native
text-PDF extraction, chunking, and embeddings have passed offline verification.
The deployed private stack enables ingestion through the explicit development
profile described below. The development auth setting
is for these private background processes; do not use it for a public API.

The VM deployment directory is `/home/developer/wbs-services`, preserving the
repository layout (`backend/` and `deploy/oracle/`). From its `deploy/oracle/`
directory, use:

```bash
docker compose -f compose.services.yml ps
docker compose -f compose.services.yml logs --tail=50 worker scheduler clamav
docker compose -f compose.services.yml up -d --build
docker compose -f compose.services.yml exec -T worker python - < verify-services.py
```

Redis and ClamAV publish ports on the VM's loopback address only
(`127.0.0.1:6379` and `127.0.0.1:3310`). Connect future application
containers to the `wbs-services_default` network using `redis:6379` and
`clamav:3310`. The Redis password is in the owner-only `redis.password` file;
the application connection URL is in owner-only `worker.env`. Do not print or
commit these files. The worker has runtime database and S3 credentials; it does
not need migration-owner credentials. Redis uses AOF, `appendfsync everysec`,
and `maxmemory-policy noeviction`; acknowledged writes can still lose roughly
one second on abrupt host failure.

ClamAV is built using Ubuntu's ARM64 packages because the upstream image checked
for this deployment only provided AMD64. Definitions persist in a Docker volume
and FreshClam checks for updates twice an hour. ClamAV reloads signatures without
concurrent engines to reduce peak memory. The configured caps are 3 GB for ClamAV,
2304 MB for the single-process worker, and 384 MB each for Redis and Beat, plus
host overhead. The worker uses one embedding CPU thread. A small native PDF was
tested on the observed 1 CPU / 6 GB VM; benchmark large files before increasing
concurrency or enabling scanned-PDF OCR. Rebuild ClamAV periodically to get updated
Ubuntu engine packages; definition updates alone do not update the engine.
When transferring source archives from Windows, set backend source file modes to
0644 and directory modes to 0755 before building, so the non-root container user
can import the application. Keep the deployment directory at 0700 and secret
files at 0600; do not apply the source permissions to secret files.

Only one scheduler may run against this queue. Beat uses the application's
existing schedules, including document deletion recovery; it may dispatch pending
deletions previously requested through the application. Retention, orphan cleanup,
and reconciliation repair modes remain disabled.

`restart: unless-stopped` restarts these services after a Docker/VM restart.
There is no automated database migration, public ingress, or retention policy
change in this deployment. `docker compose down` preserves named volumes; avoid
`down -v` because that destroys broker, signature, and scheduler state.

## Local Windows access

From the repository root in PowerShell:

```powershell
ssh -N -T -o IdentitiesOnly=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -i "$env:USERPROFILE\.ssh\id_ed25519" -L 127.0.0.1:16379:127.0.0.1:6379 -L 127.0.0.1:13310:127.0.0.1:3310 developer@144.24.43.125
```

This native SSH command needs no PowerShell execution-policy changes. It forwards
local loopback ports 16379 (Redis) and 13310 (ClamAV) to the VM's loopback service
ports. Keep the terminal open while using the services, and press Ctrl+C to stop
the tunnel. Re-run it after a reboot or after the SSH connection exits. If the
ports are already occupied by an active tunnel, use that existing connection.

Local backend settings:

```dotenv
REDIS_URL=redis://:VM_REDIS_PASSWORD@127.0.0.1:16379/0
CLAMAV_HOST=127.0.0.1
CLAMAV_PORT=13310
DOCUMENT_INGESTION_ENABLED=true
DOCUMENT_INGESTION_LOCAL_DEVELOPMENT=true
TASKS_EAGER=false
AUTO_CREATE_TABLES=false
```

Store the actual password only in the untracked `backend/.env`. Celery client
commands use the same Redis tunnel; worker and Beat have no separate listening
ports. `TASKS_EAGER=false` routes jobs to the remote worker; ingestion shares
documents through S3 and vectors through Neon. Other legacy tasks still need
their own shared-storage and runtime validation. Do not start a second Beat
instance locally against this broker.

`DOCUMENT_INGESTION_LOCAL_DEVELOPMENT` is rejected outside `APP_ENV=development`.
It permits an authenticated Redis SSH tunnel and development authentication;
PostgreSQL, separate runtime/migration roles, S3, non-eager tasks, model/tokenizer
pins, and malware scanning remain required. The API retains its existing direct
migration URL locally. The worker instead supplies only the non-secret
`DATABASE_MIGRATION_ROLE_NAME`; never give it the migration password. This role
name cannot replace production migration configuration. `verify-services.py`
checks that the connected runtime role is neither superuser nor RLS-bypassing
and is not a member of the database owner role.

The local `.env` also needs the model/tokenizer identity pins from
`worker-runtime.env`. These identify the remote model; the local API does not
need model files or OCR executables installed. Keep retention, orphan cleanup,
and reconciliation repairs disabled. Run the API from `backend` with:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Environment edits require an API restart. If ingestion returns
`DOCUMENT_INGESTION_UNREADY`, verify that the SSH tunnel is still connected.
An SSH listener left behind during a disconnect is not proof of Redis readiness.

The transport is encrypted by [OpenSSH port forwarding](https://man.openbsd.org/ssh.1#L).
The VM uses [Docker loopback bindings](https://docs.docker.com/engine/network/port-publishing/)
and requires no public Redis/ClamAV firewall openings.

## Build the OCR and embedding worker

From the Windows repository root, create a source-only build bundle and copy it
to the VM. This bundle excludes environment files and credentials:

```powershell
tar -czf deploy/oracle/ingestion-build-files.tar.gz backend/worker-constraints.txt backend/scripts/package_embedding_model.py backend/model-artifacts/bge-small-en-v1.5.manifest.json deploy/oracle/build-ingestion-worker.sh deploy/oracle/verify-worker-runtime.py
scp -o IdentitiesOnly=yes -i "$env:USERPROFILE\.ssh\id_ed25519" deploy/oracle/ingestion-build-files.tar.gz developer@144.24.43.125:/home/developer/wbs-services/
```

Connect through SSH, then run these commands on the VM:

```bash
cd /home/developer/wbs-services
tar -xzf ingestion-build-files.tar.gz
bash deploy/oracle/build-ingestion-worker.sh
```

The helper uses the existing backend Dockerfile's `ocr-worker` target, discovers
the five exact OCR package versions available in the worker's Debian base image,
and records them in `ocr-package-versions.env`. The VM host runs Ubuntu; container
package versions must come from the container's distribution. This version record
is a build candidate, not a substitute for production package/security review or
an immutable package snapshot.

The Dockerfile installs the pinned FastEmbed dependencies, downloads the model
and tokenizer using the committed integrity-checked manifest, and packages them
inside the image. Downloads happen during the build. The helper then checks the
OCR executables, English data, and a 384-dimensional embedding with networking
disabled. It prints the actual runtime OCR version settings; use
`OCRMYPDF_EXPECTED_VERSION` (without an underscore between OCRMY and PDF), as
required by the current Settings field.

The image is `wbs-ingestion-worker:local`, already selected for the worker by
Compose. The helper does not recreate containers, change credential files, or
enable ingestion. Activating ingestion still requires the remaining API/runtime
configuration and readiness checks. The API/scheduler can retain the smaller
base image. Keep only one Beat scheduler.

The helper now also generates the non-secret `worker-runtime.env` with exact OCR
versions and model/tokenizer pins. Compose applies this identity metadata to the
worker and scheduler; only the worker image contains model/OCR files. The worker
runs with a read-only root filesystem, bounded `/tmp`, and an owner-only processing
volume. After rebuilding, update only that service with:

```bash
docker compose -f compose.services.yml up -d --no-build --no-deps worker
docker compose -f compose.services.yml exec -T worker python - < verify-worker-runtime.py
```

The runtime verification uses a native text PDF and tests extraction, chunking,
and embedding without writing database rows. OCR executable/version/language
checks pass. Actual scanned/image-only PDF OCR previously returned
`DOCUMENT_PARSER_RESOURCE_EXHAUSTED` in the isolated smoke test; investigating that
path was deferred at the user's request. Do not treat scanned-PDF processing as
verified. The enabled development flow is intended for native text PDFs.

## End-to-end verification

With the tunnel open, run a temporary local API on port 8001 using the command
above with `--port 8001`. From another terminal in `backend`, run:

```powershell
.\.venv\Scripts\python.exe ..\deploy\oracle\verify-local-ingestion.py
```

This explicitly creates a small synthetic project/document, submits it through
the API, waits for the VM worker, verifies active 384-dimensional vectors in Neon,
and checks that repeating ingestion resolves to the same completed job. It keeps
the test project/document for inspection. If a tunnel interruption occurs, reuse
the printed document ID with `--document-id DOCUMENT_UUID` instead of uploading
again. This is a live integration check, separate from the offline runtime check.
