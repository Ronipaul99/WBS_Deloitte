"""Internal, scoped hybrid retrieval; scores rank evidence, not answer confidence."""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
from uuid import UUID

from app.services.ingestion.embeddings.base import EmbeddingProvider

if TYPE_CHECKING:
    from app.services.ingestion.repository import DocumentScope, VectorPersistenceRepository

_STOP_WORDS = frozenset(
    (
        "a an and are as at be by can do does for from how i in is it of on or the this to was "
        "what when where which who why with"
    ).split()
)


def lexical_terms(query: str) -> tuple[str, ...]:
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError("Query must contain 1-2000 characters")
    return tuple(
        dict.fromkeys(
            word for word in re.findall(r"[^\W_]+", query.lower()) if word not in _STOP_WORDS
        )
    )[:64]


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    chunk_id: UUID
    processing_run_id: UUID
    ordinal: int
    content: str
    page_numbers: tuple[int, ...]
    heading_path: tuple[str, ...]
    score: float
    cosine_similarity: float
    reranker_score: float | None = None
    evidence_status: str = "unverified_candidate"


def fuse_candidates(semantic, lexical, *, limit: int) -> tuple[RetrievalHit, ...]:
    scores: dict[UUID, float] = {}
    records = {}
    for stream in (semantic, lexical):
        seen = set()
        for rank, row in enumerate(stream, start=1):
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            scores[row["id"]] = scores.get(row["id"], 0) + 1 / (60 + rank)
            records[row["id"]] = row
    ordered = sorted(scores, key=lambda key: (-scores[key], records[key]["ordinal"], str(key)))
    return tuple(
        RetrievalHit(
            key,
            records[key]["processing_run_id"],
            records[key]["ordinal"],
            records[key]["content"],
            tuple(records[key]["source_metadata"].get("page_numbers", [])),
            tuple(records[key]["heading_path"]),
            scores[key],
            1 - float(records[key]["distance"]),
        )
        for key in ordered[:limit]
    )


class HybridRetriever:
    def __init__(
        self, repository: VectorPersistenceRepository, provider: EmbeddingProvider, *, reranker=None
    ):
        self.repository = repository
        self.provider = provider
        self.reranker = reranker

    async def search(self, scope: DocumentScope, query: str, *, limit: int = 5):
        terms = lexical_terms(query)
        if not terms:
            return ()
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ValueError("Retrieval limit must be between 1 and 20")
        vector = await asyncio.to_thread(self.provider.embed_query, query)
        semantic, lexical = await self.repository.active_search_candidates(
            scope,
            vector,
            terms=terms,
            candidate_limit=30,
        )
        candidates = fuse_candidates(semantic, lexical, limit=60)
        if not candidates:
            return ()
        from app.services.ingestion.reranking import get_reranker

        reranker = self.reranker or await asyncio.to_thread(get_reranker)
        scores = await asyncio.to_thread(
            reranker.score,
            query,
            [" > ".join(hit.heading_path) + "\n" + hit.content for hit in candidates],
        )
        if len(scores) != len(candidates) or not all(math.isfinite(score) for score in scores):
            raise ValueError("Reranker result count mismatch")
        ranked = [
            replace(hit, reranker_score=score)
            for hit, score in zip(candidates, scores, strict=True)
        ]
        return tuple(
            sorted(
                ranked,
                key=lambda hit: (
                    -hit.reranker_score,
                    -hit.score,
                    hit.ordinal,
                    str(hit.chunk_id),
                ),
            )[:limit]
        )
