from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from embedding_fixtures import MODEL_REVISION, verified_manifest

from app.services.ingestion.embeddings.base import EmbeddingPolicy
from app.services.ingestion.embeddings.fastembed_provider import (
    FastEmbedProvider,
    _create_fastembed_engine,
)
from app.services.ingestion.errors import EmbeddingError, EmbeddingErrorCode


def raw_vector(value: float = 0.25):
    return [value] * 384


class RecordingEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def embed(self, documents, *, batch_size, parallel):
        values = tuple(documents)
        self.calls.append(values)
        assert batch_size == len(values)
        assert parallel is None
        return (raw_vector(float(index + 1)) for index, _ in enumerate(values))


def provider(tmp_path, engine, **policy_overrides) -> FastEmbedProvider:
    policy = EmbeddingPolicy(**policy_overrides)
    return FastEmbedProvider(
        manifest=verified_manifest(tmp_path),
        policy=policy,
        engine_factory=lambda _root, _policy: engine,
    )


def test_documents_are_unchanged_batched_and_returned_in_order(tmp_path) -> None:
    engine = RecordingEngine()
    adapter = provider(tmp_path, engine, batch_size=2)
    documents = ("first passage", "second passage", "third passage")

    vectors = adapter.embed_documents(documents)

    assert engine.calls == [("first passage", "second passage"), ("third passage",)]
    assert tuple(vector.values[0] for vector in vectors) == (1.0, 2.0, 1.0)
    assert tuple(adapter.format_document(text) for text in documents) == documents


def test_query_uses_the_fixed_versioned_instruction(tmp_path) -> None:
    engine = RecordingEngine()
    adapter = provider(tmp_path, engine)

    result = adapter.embed_query("project delivery risks")

    assert result.dimensions == 384
    assert engine.calls == [
        ("Represent this sentence for searching relevant passages: project delivery risks",)
    ]
    assert adapter.formatting_version == "bge-small-en-v1.5-format-v1"


def test_empty_input_returns_without_initializing_the_model(tmp_path) -> None:
    calls = 0

    def factory(_root, _policy):
        nonlocal calls
        calls += 1
        return RecordingEngine()

    adapter = FastEmbedProvider(
        manifest=verified_manifest(tmp_path),
        policy=EmbeddingPolicy(),
        engine_factory=factory,
    )

    assert adapter.embed_documents(()) == ()
    assert calls == 0


@pytest.mark.parametrize(
    "runtime_output",
    [
        [],
        [raw_vector(), raw_vector()],
        [[0.0] * 383],
        [[0.0] * 385],
        [[0.0] * 383 + [float("nan")]],
        [[0.0] * 383 + [float("inf")]],
        [[0.0] * 383 + [True]],
        [[0.0] * 383 + ["private-content-marker"]],
    ],
)
def test_invalid_model_output_fails_without_returning_partial_vectors(
    tmp_path, runtime_output
) -> None:
    class InvalidEngine:
        def embed(self, documents, *, batch_size, parallel):
            return iter(runtime_output)

    adapter = provider(tmp_path, InvalidEngine())

    with pytest.raises(EmbeddingError) as error:
        adapter.embed_documents(("synthetic passage",))
    assert error.value.code is EmbeddingErrorCode.EMBEDDING_OUTPUT_INVALID
    assert "private-content-marker" not in str(error.value)


def test_input_count_and_character_limits_are_enforced_before_initialization(tmp_path) -> None:
    initialized = False

    def factory(_root, _policy):
        nonlocal initialized
        initialized = True
        return RecordingEngine()

    adapter = FastEmbedProvider(
        manifest=verified_manifest(tmp_path),
        policy=EmbeddingPolicy(
            maximum_inputs=2,
            maximum_text_characters=5,
            maximum_aggregate_characters=8,
        ),
        engine_factory=factory,
    )

    with pytest.raises(EmbeddingError) as too_many:
        adapter.embed_documents(text for text in ("one", "two", "tri"))
    assert too_many.value.code is EmbeddingErrorCode.DOCUMENT_EMBEDDING_LIMIT_EXCEEDED
    assert initialized is False

    with pytest.raises(EmbeddingError):
        adapter.embed_documents(("oversized",))
    assert initialized is False


def test_initialization_is_process_aware_and_failed_initialization_is_not_cached(
    tmp_path, monkeypatch
) -> None:
    calls = 0

    def factory(_root, _policy):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("private-model-path-marker")
        return RecordingEngine()

    adapter = FastEmbedProvider(
        manifest=verified_manifest(tmp_path),
        policy=EmbeddingPolicy(),
        engine_factory=factory,
    )
    with pytest.raises(EmbeddingError) as first:
        adapter.embed_documents(("first",))
    assert first.value.code is EmbeddingErrorCode.EMBEDDING_RUNTIME_UNAVAILABLE

    assert adapter.embed_documents(("second",))[0].dimensions == 384
    monkeypatch.setattr(
        "app.services.ingestion.embeddings.fastembed_provider.os.getpid", lambda: 987654
    )
    assert adapter.embed_documents(("third",))[0].dimensions == 384
    assert calls == 3


def test_batch_concurrency_is_bounded(tmp_path) -> None:
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    class SlowEngine:
        def embed(self, documents, *, batch_size, parallel):
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            try:
                time.sleep(0.03)
                return iter([raw_vector()])
            finally:
                with lock:
                    active -= 1

    adapter = provider(tmp_path, SlowEngine(), maximum_concurrent_batches=1)
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = tuple(executor.map(lambda value: adapter.embed_documents((value,)), "abc"))

    assert all(batch[0].dimensions == 384 for batch in results)
    assert maximum_active == 1


def test_default_factory_forces_local_cpu_only_fastembed(monkeypatch, tmp_path) -> None:
    captured = {}
    sentinel = object()

    def fake_text_embedding(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr("fastembed.TextEmbedding", fake_text_embedding)

    result = _create_fastembed_engine(tmp_path, EmbeddingPolicy(cpu_threads=3))

    assert result is sentinel
    assert captured == {
        "model_name": "BAAI/bge-small-en-v1.5",
        "cache_dir": str(tmp_path),
        "threads": 3,
        "providers": ["CPUExecutionProvider"],
        "lazy_load": False,
        "local_files_only": True,
        "specific_model_path": str(tmp_path),
    }


def test_unexpected_embedding_failure_is_redacted_from_error_and_logs(tmp_path, caplog) -> None:
    marker = "private-path-filename-object-key-endpoint-content-marker"

    class FailingEngine:
        def embed(self, documents, *, batch_size, parallel):
            raise RuntimeError(marker)

    adapter = provider(tmp_path, FailingEngine())
    with pytest.raises(EmbeddingError) as error:
        adapter.embed_documents(("synthetic content",))

    assert error.value.code is EmbeddingErrorCode.DOCUMENT_EMBEDDING_FAILED
    assert marker not in str(error.value)
    assert marker not in caplog.text


def test_provider_metadata_is_explicit_and_pinned(tmp_path) -> None:
    adapter = provider(tmp_path, RecordingEngine())

    assert adapter.provider_name == "fastembed"
    assert adapter.model_name == "BAAI/bge-small-en-v1.5"
    assert adapter.model_revision == MODEL_REVISION
    assert adapter.dimensions == 384
