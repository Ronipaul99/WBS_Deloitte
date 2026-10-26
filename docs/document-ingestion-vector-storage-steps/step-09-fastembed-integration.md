# Step 9: Package and Integrate FastEmbed

## Step Status

Repository implementation complete as of 2026-10-26. Release-worker verification remains blocked
by the external gates recorded in `step-09-artifacts/implementation-evidence.md`.

## Objective

Generate one validated 384-dimensional embedding for every canonical chunk using a pinned,
build-time-packaged `BAAI/bge-small-en-v1.5` model. Runtime ingestion must work without downloading
model artifacts or sending document text to an external embedding API.

## Prerequisites

- Step 1 embedding configuration validated.
- Step 8 provides bounded canonical chunks.
- Approved FastEmbed and model revisions, checksums, and licenses recorded.
- Worker CPU/memory limits and concurrency target established.
- Release artifact repository/build environment can fetch the model during an approved build stage.

## Provider Contract

Define an application-owned interface:

```python
class EmbeddingProvider(Protocol):
    provider_name: str
    model_name: str
    model_revision: str
    dimensions: int

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...
    def embed_query(self, text: str) -> Sequence[float]: ...
```

Only `embed_documents` is required for this feature. Define `embed_query` consistently for internal
verification and future retrieval, including the BGE query instruction policy. Do not add an
external-provider fallback.

## Build-Time Model Packaging

1. Pin FastEmbed and transitive runtime expectations.
2. Pin an immutable model revision rather than a floating model name alone.
3. Download artifacts in the Docker builder stage through the approved network path.
4. Verify expected filenames, licenses, sizes, and cryptographic checksums.
5. Copy the model/cache into `/opt/wbs-models/bge-small-en-v1.5` in the runtime worker image.
6. Set ownership to root/build owner and read permission for the non-root worker user.
7. Prevent runtime modification where the platform supports a read-only filesystem.
8. Run an offline model-load and fixture-embedding check during image verification.

Do not rely on a mutable user home cache or a first-request model download.

## Runtime Behavior

- Initialize one model instance per Celery worker process.
- Keep initialization outside individual chunk loops.
- Batch canonical content using the configured batch size.
- Bound worker process concurrency based on measured CPU and memory.
- Preserve input order in output vectors.
- Reject missing, extra, non-finite, or incorrectly sized vectors.
- Record model metadata on the processing run.
- Do not log texts or vectors.
- Do not persist partial embedding batches as an active run.

## BGE Formatting Policy

- Embed stored document passages without a query instruction.
- For future retrieval queries, use the approved BGE query instruction consistently.
- Keep formatting logic in the provider so callers cannot accidentally mix conventions.
- Version any formatting-policy change because it may require re-embedding.

## Implementation Tasks

1. Add pinned `fastembed` and tokenizer dependencies.
2. Add embedding-provider protocol and typed result validation.
3. Implement `FastEmbedProvider` with packaged model path.
4. Implement lazy process-level initialization with explicit readiness warm-up.
5. Implement bounded batching and order preservation.
6. Validate vector count, numeric type, finiteness, and dimension.
7. Add document/query formatting methods.
8. Add worker metrics for initialization and batch duration.
9. Update Docker build to package and verify model artifacts.
10. Add image/license inventory documentation.

## Files Expected to Change

- `backend/pyproject.toml`
- `backend/Dockerfile`
- `backend/app/services/ingestion/embeddings/base.py`
- `backend/app/services/ingestion/embeddings/fastembed_provider.py`
- worker readiness
- embedding unit/integration tests
- release dependency/model inventory

## Test Matrix

- offline provider initialization;
- known single and batched inputs;
- order preserved across multiple batches;
- empty input handling;
- exactly 384 finite values per result;
- simulated missing, short, long, NaN, and infinite vectors;
- unreadable/corrupt model path;
- runtime network unavailable;
- concurrent worker processes under memory target;
- document versus query formatting;
- provider/model metadata recorded;
- no content/vector leakage in logs or traces.

Do not assert byte-for-byte floating-point equality across unrelated hardware unless the runtime and
ONNX execution provider guarantee it. Assert dimensional, finite, normalization/ranking, and fixture
behavior appropriate to the selected runtime.

## Security Checklist

- [x] Model and dependency versions are pinned.
- [x] Artifact checksums and licenses are recorded.
- [x] No remote code execution or `trust_remote_code` path is enabled.
- [x] Host verification proves runtime network is not required for embeddings.
- [ ] Model directory is proven read-only in the release worker.
- [x] Repository tests prove texts and vectors are absent from application logs and metrics.
- [ ] Release CPU, memory, batch, and concurrency values are supported by measured capacity evidence.

## Performance Evidence

Measure with representative chunk sizes:

- cold worker model-load time;
- warm batch latency for configured batch size;
- chunks per second;
- peak resident memory per worker process;
- effect of Celery concurrency;
- total embedding time for maximum accepted document.

Use evidence to set worker concurrency and autoscaling. Do not tune batch size solely for a developer
machine.

## Verification

Build the actual release worker image, disconnect runtime model-download access, start worker
readiness, and embed a fixture batch. Verify the output dimension and internal exact vector query in
an isolated test flow.

## Rollback

Disable ingestion creation if the packaged model fails. Retain uploaded originals and previous active
runs. Changing model name, revision, dimension, or formatting policy requires a versioned reprocessing
plan rather than silently mixing vectors.

## Exit Criteria

- [ ] Release worker image contains the pinned model and license inventory.
- [ ] Release worker initializes and embeds with no runtime download.
- [x] Repository and real host verification produce finite 384-dimensional output.
- [x] Batch order and error handling tests pass.
- [ ] CPU/memory/concurrency evidence is recorded.
- [x] No external embedding API or fallback exists.

## Handoff to Step 10

Provide ordered chunk/vector pairs plus provider, model, revision, dimension, and formatting version.
Step 10 validates and writes them transactionally to the run created in Step 3.

