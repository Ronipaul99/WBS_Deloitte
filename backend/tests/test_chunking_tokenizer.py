import hashlib

import pytest
from chunking_fixtures import CharacterTokenizer

from app.core.config import Settings
from app.services import readiness
from app.services.ingestion.errors import ChunkingError, ChunkingErrorCode
from app.services.ingestion.tokenizer import LocalBgeTokenizer


def tokenizer_settings(model_path: str, **overrides: object) -> Settings:
    values = {
        "embedding_model_path": model_path,
        "embedding_tokenizer_revision": "approved-revision",
        "embedding_tokenizer_sha256": "a" * 64,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_local_tokenizer_rejects_missing_and_integrity_mismatched_artifacts(tmp_path) -> None:
    settings = tokenizer_settings(str(tmp_path / "missing"))
    with pytest.raises(ChunkingError) as missing:
        LocalBgeTokenizer.from_settings(settings)
    assert missing.value.code is ChunkingErrorCode.TOKENIZER_ARTIFACT_INVALID

    root = tmp_path / "model"
    root.mkdir()
    (root / "tokenizer.json").write_text("{}", encoding="utf-8")
    (root / "tokenizer-revision.txt").write_text("approved-revision", encoding="ascii")
    settings = tokenizer_settings(str(root), embedding_tokenizer_sha256="b" * 64)
    with pytest.raises(ChunkingError) as mismatch:
        LocalBgeTokenizer.from_settings(settings)
    assert mismatch.value.code is ChunkingErrorCode.TOKENIZER_ARTIFACT_INVALID


def test_local_tokenizer_rejects_revision_mismatch_without_revealing_details(tmp_path) -> None:
    root = tmp_path / "private-model-location"
    root.mkdir()
    artifact = b"{}"
    (root / "tokenizer.json").write_bytes(artifact)
    (root / "tokenizer-revision.txt").write_text("wrong-revision", encoding="ascii")
    settings = tokenizer_settings(
        str(root), embedding_tokenizer_sha256=hashlib.sha256(artifact).hexdigest()
    )

    with pytest.raises(ChunkingError) as error:
        LocalBgeTokenizer.from_settings(settings)

    assert str(root) not in str(error.value)
    assert "wrong-revision" not in str(error.value)


def test_local_tokenizer_loads_only_integrity_pinned_local_artifact(tmp_path) -> None:
    tokenizers = pytest.importorskip("tokenizers")
    models = pytest.importorskip("tokenizers.models")
    pre_tokenizers = pytest.importorskip("tokenizers.pre_tokenizers")
    processors = pytest.importorskip("tokenizers.processors")
    root = tmp_path / "model"
    root.mkdir()
    tokenizer = tokenizers.Tokenizer(
        models.WordLevel(
            vocab={"[UNK]": 0, "[CLS]": 1, "[SEP]": 2, "bounded": 3, "test": 4},
            unk_token="[UNK]",
        )
    )
    tokenizer.add_special_tokens(["[CLS]", "[SEP]"])
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]",
        special_tokens=[("[CLS]", 1), ("[SEP]", 2)],
    )
    artifact_path = root / "tokenizer.json"
    tokenizer.save(str(artifact_path))
    (root / "tokenizer-revision.txt").write_text("approved-revision", encoding="ascii")
    settings = tokenizer_settings(
        str(root),
        embedding_tokenizer_sha256=hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
    )

    adapter = LocalBgeTokenizer.from_settings(settings)

    assert adapter.count("bounded test") == 4
    assert adapter.decode(adapter.encode("bounded test")) == "bounded test"


def test_worker_tokenizer_readiness_accepts_injected_contract_and_redacts_failure() -> None:
    tokenizer = CharacterTokenizer()
    settings = tokenizer_settings(
        "/approved/model",
        embedding_tokenizer_revision=tokenizer.revision,
    )
    readiness.tokenizer_runtime_is_ready(settings, tokenizer)

    class FailingTokenizer(CharacterTokenizer):
        def self_check(self) -> None:
            raise RuntimeError("private-path secret-marker endpoint-marker")

    with pytest.raises(readiness.IngestionReadinessError) as error:
        readiness.tokenizer_runtime_is_ready(settings, FailingTokenizer())
    assert error.value.category == "tokenizer_runtime"
    assert "secret-marker" not in str(error.value)


async def test_api_readiness_never_constructs_tokenizer(monkeypatch) -> None:
    settings = Settings(_env_file=None, document_ingestion_enabled=False)

    def unexpected(*_args, **_kwargs) -> None:
        raise AssertionError("API readiness constructed tokenizer")

    monkeypatch.setattr(readiness, "tokenizer_runtime_is_ready", unexpected)
    await readiness.api_ingestion_is_ready(settings)
