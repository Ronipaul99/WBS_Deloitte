"""Use the application's pinned, locally verified FastEmbed artifact for queries."""

from collections.abc import Sequence
from functools import lru_cache

from app.core.config import Settings
from app.services.ingestion.embeddings.fastembed_provider import FastEmbedProvider
from question_doc.question_bank import EMBEDDING_MODEL, QUERY_PREFIX


@lru_cache(maxsize=1)
def get_model() -> FastEmbedProvider:
    return build_provider(Settings())


def build_provider(settings: Settings) -> FastEmbedProvider:
    if settings.embedding_model != EMBEDDING_MODEL:
        raise ValueError("Question and document embedding models must match")
    if FastEmbedProvider.format_query("") != QUERY_PREFIX:
        raise ValueError("Question and document query formatting must match")
    # Local operator tooling verifies hashes without requiring a read-only mount.
    # Production workers retain their existing read-only artifact requirement.
    return FastEmbedProvider.from_settings(settings)


def embed_documents(texts: Sequence[str]) -> list[list[float]]:
    return [list(vector.values) for vector in get_model().embed_documents(texts)]


def embed_questions(texts: Sequence[str]) -> list[list[float]]:
    return [list(get_model().embed_query(text).values) for text in texts]
