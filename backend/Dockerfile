FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.12-slim AS runtime-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/wbs/.local/bin:${PATH}"

RUN groupadd --system wbs && useradd --system --gid wbs --create-home wbs
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/* && rm -rf /wheels
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations

FROM python:3.12-slim AS worker-dependency-builder

WORKDIR /app
COPY pyproject.toml ./
COPY worker-constraints.txt ./
COPY app ./app
RUN python -m pip wheel --no-cache-dir --constraint worker-constraints.txt \
        --wheel-dir /worker-wheels ".[worker]"

FROM python:3.12-slim AS embedding-model-builder

WORKDIR /build
COPY scripts/package_embedding_model.py ./package_embedding_model.py
COPY model-artifacts/bge-small-en-v1.5.manifest.json ./model-manifest.json
RUN python ./package_embedding_model.py \
        --manifest ./model-manifest.json \
        --manifest-sha256 609e3f5b2f42b5c302c9fd86344b7c9f1cb498fa2f29826b1265da284dc18ca0 \
        --destination /opt/wbs-models/bge-small-en-v1.5

FROM python:3.12-slim AS reranker-model-builder
WORKDIR /build
COPY scripts/package_embedding_model.py ./package_embedding_model.py
COPY model-artifacts/ms-marco-MiniLM-L-6-v2.manifest.json ./reranker-manifest.json
RUN python ./package_embedding_model.py \
        --manifest ./reranker-manifest.json \
        --manifest-sha256 c4aa06cd6796025da53c16ae437049965eea2c3d1172ece0ad951a0b61ebf773 \
        --destination /opt/wbs-models/ms-marco-MiniLM-L-6-v2

FROM runtime-base AS ocr-worker

ARG OCRMY_PDF_PACKAGE_VERSION
ARG TESSERACT_OCR_PACKAGE_VERSION
ARG TESSERACT_ENG_PACKAGE_VERSION
ARG GHOSTSCRIPT_PACKAGE_VERSION
ARG QPDF_PACKAGE_VERSION

COPY --from=worker-dependency-builder /worker-wheels /worker-wheels
COPY worker-constraints.txt /tmp/worker-constraints.txt
COPY --from=embedding-model-builder /opt/wbs-models /opt/wbs-models
COPY --from=reranker-model-builder /opt/wbs-models/ms-marco-MiniLM-L-6-v2 /opt/wbs-models/ms-marco-MiniLM-L-6-v2

RUN test -n "$OCRMY_PDF_PACKAGE_VERSION" \
    && test -n "$TESSERACT_OCR_PACKAGE_VERSION" \
    && test -n "$TESSERACT_ENG_PACKAGE_VERSION" \
    && test -n "$GHOSTSCRIPT_PACKAGE_VERSION" \
    && test -n "$QPDF_PACKAGE_VERSION" \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        "ocrmypdf=$OCRMY_PDF_PACKAGE_VERSION" \
        "tesseract-ocr=$TESSERACT_OCR_PACKAGE_VERSION" \
        "tesseract-ocr-eng=$TESSERACT_ENG_PACKAGE_VERSION" \
        "ghostscript=$GHOSTSCRIPT_PACKAGE_VERSION" \
        "qpdf=$QPDF_PACKAGE_VERSION" \
    && python -m pip install --no-cache-dir --no-index --find-links=/worker-wheels \
        --constraint /tmp/worker-constraints.txt \
        "fastembed==0.9.0" "tokenizers==0.22.2" \
    && rm -rf /worker-wheels \
    && rm -f /tmp/worker-constraints.txt \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -o wbs -g wbs -m 0700 /var/lib/wbs/processing \
    && chown -R root:root /opt/wbs-models \
    && find /opt/wbs-models -type d -exec chmod 0555 {} + \
    && find /opt/wbs-models -type f -exec chmod 0444 {} + \
    && chmod -R a-w /app /home/wbs

ENV DOCUMENT_PROCESSING_TEMP_ROOT=/var/lib/wbs/processing \
    HOME=/var/lib/wbs/processing \
    TMPDIR=/var/lib/wbs/processing \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    FASTEMBED_CACHE_PATH=/opt/wbs-models

USER wbs

RUN python -c "from fastembed import TextEmbedding; m=TextEmbedding(model_name='BAAI/bge-small-en-v1.5', specific_model_path='/opt/wbs-models/bge-small-en-v1.5', local_files_only=True, providers=['CPUExecutionProvider'], threads=2); v=list(m.embed(['offline image verification'], batch_size=1, parallel=None)); assert len(v) == 1 and len(v[0]) == 384"
RUN python -c "from app.services.ingestion.reranking import get_reranker; scores=get_reranker().score('What is the capital of France?', ['Paris is the capital of France.', 'The bicycle has two wheels.']); assert len(scores) == 2 and scores[0] > scores[1]"

CMD ["celery", "-A", "app.worker.celery_app", "worker", "--loglevel=INFO"]

FROM runtime-base AS runtime

USER wbs

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=3)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

