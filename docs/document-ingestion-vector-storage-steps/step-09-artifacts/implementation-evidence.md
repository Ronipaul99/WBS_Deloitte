# Step 9 Implementation Evidence

## Status

The Step 9 repository implementation is complete as of 2026-10-26. A real immutable model snapshot
was packaged, checksum-verified, initialized offline, and used to produce one finite 384-dimensional
fixture vector on this host. Step 9 is not release-worker verified: Docker is unavailable, container
ownership/read-only/network isolation was not executed, representative CPU/memory/performance and
multi-process capacity were not measured, organizational dependency/model approval is pending, and
the vulnerability gate fails. `DOCUMENT_INGESTION_ENABLED` must remain false.

## Changed Files

- `backend/app/services/ingestion/embeddings/__init__.py`
- `backend/app/services/ingestion/embeddings/base.py`
- `backend/app/services/ingestion/embeddings/manifest.py`
- `backend/app/services/ingestion/embeddings/fastembed_provider.py`
- `backend/app/services/ingestion/errors.py`
- `backend/app/services/readiness.py`
- `backend/app/core/config.py`
- `backend/app/core/observability.py`
- `backend/app/cli.py`
- `backend/pyproject.toml`
- `backend/worker-constraints.txt`
- `backend/Dockerfile`
- `backend/scripts/package_embedding_model.py`
- `backend/model-artifacts/bge-small-en-v1.5.manifest.json`
- `backend/model-artifacts/README.md`
- `backend/.env.example`
- `backend/README.md`
- Focused embedding fixture, contract, provider, manifest, error, readiness, packaging,
  observability, and configuration tests
- Narrow updates to existing ingestion-readiness and release-configuration fixtures
- The Step 9 execution document and this evidence file

No extraction/OCR behavior, normalization/chunking behavior, FastAPI route, React file, database
model, migration, processing-run/chunk/vector persistence, vector search, task/orchestration,
summary, RAG, LLM, agentic workflow, or Step 10 functionality was added.

## Contract And Handoff

`EmbeddingProvider` exposes fixed document and query embedding operations plus explicit provider,
model, revision, dimension, and formatting metadata. Values are frozen and bounded. A vector accepts
only 384 real, finite, non-boolean values and stores them as an immutable tuple with a redacted
representation.

`embed_canonical_chunks` consumes ordered Step 8 `CanonicalChunk` values, passes only unchanged
canonical content to the provider, and returns immutable ordered chunk/vector pairs. Each pair
retains the original chunk object, ordinal, SHA-256, source provenance, and vector. Neither chunk
content nor vector values appear in representations. Missing, extra, reordered, malformed, or
partial vectors fail before a result exists. This is the typed Step 10 handoff; it performs no write.

Stable embedding errors cover runtime unavailability, invalid packaged model, document embedding
limits, invalid output, and unexpected embedding failure. Job mappings contain only stable code,
retryability, and a fixed message. No raw model, ONNX, path, input, vector, or dependency exception
is returned.

## Model And Dependency Inventory

- Provider: `fastembed`.
- Application model: `BAAI/bge-small-en-v1.5`.
- FastEmbed artifact repository: `Qdrant/bge-small-en-v1.5-onnx-Q`.
- Immutable artifact revision: `aa8f8b060edb00e03bfdd08813a2949946c8ba55`.
- Original BAAI provenance revision: `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`.
- Dimensions: 384.
- Formatting version: `bge-small-en-v1.5-format-v1`.
- Manifest SHA-256: `609e3f5b2f42b5c302c9fd86344b7c9f1cb498fa2f29826b1265da284dc18ca0`.
- Model license: MIT from immutable FlagEmbedding revision
  `fd1a2bdf69488ffebe0327999d4400d8c8058a0b`.
- Worker runtime: `fastembed==0.9.0`, `onnxruntime==1.31.0`, `numpy==2.5.4`,
  `tokenizers==0.22.2`, and an exact transitive closure enforced from
  `backend/worker-constraints.txt` during worker wheel creation and installation.

The FastEmbed PyPI wheel has SHA-256
`273d408edec8c0f161711d8f6e44e4a5b559d18e8edf6bf805415d55dc772846` and no PyPI provenance
attestation. These are verified public technical pins, not organizational approval.

## Artifact And Runtime Controls

The manifest verifier resolves one non-symlink root, requires exactly the allowlisted model,
tokenizer, configuration, revision, and license files, bounds manifest/file/aggregate sizes, and
checks every exact size and SHA-256. Unknown, missing, modified, duplicated, traversal, symlinked,
unreadable, writable-in-release-readiness, wrong-revision, wrong-model, wrong-dimension, wrong-license,
or wrong-tokenizer artifacts fail closed without exposing a path or digest.

The provider imports FastEmbed lazily in the worker, forces `specific_model_path`,
`local_files_only=True`, `CPUExecutionProvider`, fixed threads, and no remote-code or external
provider path. It owns the BGE formatting rule: document passages are unchanged and queries receive
`Represent this sentence for searching relevant passages: ` under a versioned policy.

Initialization is locked, PID-aware, once per process, and retried after failure rather than caching
a broken instance. Empty input does not initialize the model. Input count, per-text and aggregate
characters, batch size, CPU threads, and concurrent batches are bounded. The current release gate
forces one concurrent embedding batch per worker process until capacity evidence approves a change.
Output iteration reads at most expected count plus one, preserves batch/input order, and rejects
missing, extra, non-real, boolean, short, long, NaN, or infinite vectors.

## Docker And Readiness Design

The worker dependency builder resolves the exact worker group into a wheelhouse under the checked-in
worker constraints lock; worker installation enforces the same lock. A separate model builder
downloads only immutable HTTPS sources on allowlisted public hosts and verifies all bytes.
Only `ocr-worker` receives the wheelhouse and `/opt/wbs-models`; files are made root-owned, directories
`0555`, and files `0444`. The non-root worker stage sets offline environment flags and runs a fixed
offline 384-dimensional fixture check. The API `runtime` target inherits none of those additions.

API readiness remains Redis-only for ingestion dispatch and does not call embedding readiness,
import FastEmbed/ONNX, inspect model artifacts, or embed text. Worker readiness validates the local
model and tokenizer, constructs the process-local provider, embeds one fixed synthetic string, and
reports only the safe `embedding_runtime` category on failure.

Metrics record initialization and batch duration, numeric input counts, and allowlisted outcomes.
They do not label content, vectors, hashes, paths, filenames, IDs, tenant/project/document data,
endpoints, model output, or exception text.

## Verification Evidence

Focused Step 9 configuration, contract, manifest, provider, errors, readiness, packaging, and
observability tests:

```text
129 passed, 1 skipped, 1 warning in 6.12s
```

The skip is the Windows-host symlink-creation gate. Step 8 regression tests rerun sequentially:

```text
20 passed, 1 warning in 0.30s
```

Authentication, authorization, and SSO dependency regression selection:

```text
41 passed, 1 warning in 11.01s
```

Complete backend suite:

```text
465 passed, 5 skipped, 1 warning in 41.56s
```

The remaining skips are existing Windows symlink/PostgreSQL integration gates. The warning is the
existing Starlette TestClient deprecation warning; the project deliberately did not install
`httpx2`, which previously changed authentication cookie behavior.

Real host artifact/offline check:

```text
immutable manifest download and all file hashes: passed
application manifest verification: passed
FastEmbed local_files_only initialization with offline environment: passed
document fixture vectors: 2
query fixture vectors with fixed formatting: 1
dimensions: 384
all values finite: true
temporary model directory cleanup: passed
```

Quality and dependency consistency:

```text
python -m ruff check <Step 9 Python files>
All checks passed!

python -m ruff format --check <Step 9 Python files>
23 files already formatted

python -m pip check
No broken requirements found.

git diff --check
Exit 0; existing line-ending notices only.
```

The host verification proves the recorded snapshot and provider API work offline. It does not prove
the Docker targets, read-only container filesystem, non-root runtime, or release infrastructure.

## Vulnerability Result

`pip-audit` reported 59 advisory records affecting five packages. Certifi, cryptography, pip, and
development-only pytest were pre-existing findings. Pillow `12.3.0` is new through FastEmbed and has
advisories fixed in `13.0.0`, while FastEmbed `0.9.0` declares `pillow<13`. No advisory was reported
for FastEmbed, ONNX Runtime, NumPy, tokenizers, Hugging Face Hub, Loguru, mmh3, protobuf,
py-rust-stemmers, requests, tqdm, or flatbuffers. The vulnerability gate remains failed.

## External Release Gates

- Obtain organizational security and license approval for FastEmbed, the converted Qdrant snapshot,
  the original BAAI model, and every pinned dependency.
- Resolve or formally disposition Pillow's incompatible security update and every pre-existing
  audit finding; do not release with an unapproved exception.
- Build and scan the API and worker images; Docker was unavailable in this environment.
- Prove the API image contains no FastEmbed, ONNX Runtime, tokenizer runtime, model, or license
  payload.
- Prove the worker runs non-root, the model directory is root-owned/read-only, and runtime network
  disconnection cannot trigger a model download.
- Run native release-worker offline initialization, document/query fixtures, error/redaction paths,
  and the isolated exact pgvector query handoff.
- Measure cold initialization, configured-batch latency, chunks per second, peak RSS per worker,
  concurrent-process memory, temporary disk, maximum-document duration, and autoscaling behavior.
- Use those measurements to approve Celery concurrency, CPU/memory limits, and timeouts.
- Inspect deployed logs, metrics, traces, crash reports, and readiness responses for disclosure.

## Residual Risks And Step 10 Handoff

- The Dockerfile's intended API/worker separation is statically tested but not built here.
- FastEmbed's current Pillow constraint blocks a clean vulnerability gate.
- One model instance per process and the semaphore are repository-tested; multi-process peak memory
  and capacity remain unmeasured.
- Floating-point bytes are intentionally not compared across unrelated hardware. Release fixtures
  must validate dimensions, finiteness, normalization/ranking, and deterministic order on the
  approved ONNX provider/runtime.
- Step 10 must consume `EmbeddingBatchResult`, attach the already-authorized tenant/project/document
  processing scope, revalidate metadata/dimensions/order, and persist all chunks/vectors atomically.
  It must never activate a partial run or mix model/formatting versions.
