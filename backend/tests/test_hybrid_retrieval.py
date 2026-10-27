from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.ingestion.query_aliases import expand_alias_terms
from app.services.ingestion.retrieval import HybridRetriever, fuse_candidates, lexical_terms


def test_query_terms_are_bounded_and_not_tsquery_syntax():
    assert lexical_terms("What is the term of the PPA?") == ("term", "ppa")
    assert lexical_terms("'; DROP TABLE x -- | !") == ("drop", "table", "x")
    with pytest.raises(ValueError):
        lexical_terms("x" * 2001)


def test_only_explicit_unambiguous_glossary_aliases_expand_lexical_terms():
    paths = [("GLOSSARY", "Request for Proposal or RFP")]
    assert expand_alias_terms(("rfp",), paths) == ("rfp", "request", "for", "proposal")
    assert "rfp" in expand_alias_terms(("request", "for", "proposal"), paths)
    assert expand_alias_terms(("rfp",), [("Other", "Request for Proposal or RFP")]) == ("rfp",)
    assert expand_alias_terms(("rfp",), [*paths, ("GLOSSARY", "Another Meaning or RFP")]) == (
        "rfp",
    )


def test_reranker_scores_bounded_windows_and_returns_one_score_per_chunk():
    import threading

    import numpy as np

    from app.services.ingestion.reranking import OnnxReranker

    class Tokenizer:
        def no_truncation(self):
            pass

        def enable_truncation(self, **kwargs):
            pass

        def encode(self, value, **kwargs):
            return SimpleNamespace(ids=list(value), offsets=[(i, i + 1) for i in range(len(value))])

        def encode_batch(self, pairs):
            assert len(pairs) <= 4
            assert all(len(value) <= 380 for _, value in pairs)
            return [
                SimpleNamespace(ids=[int("ANSWER" in value)], attention_mask=[1], type_ids=[0])
                for _, value in pairs
            ]

    class Session:
        def get_inputs(self):
            return [SimpleNamespace(name="input_ids")]

        def run(self, _, features):
            return [np.asarray(features["input_ids"], dtype=float)]

    reranker = OnnxReranker.__new__(OnnxReranker)
    reranker.tokenizer = Tokenizer()
    reranker.session = Session()
    reranker._lock = threading.Lock()
    assert reranker.score("term", ["x" * 450 + "ANSWER" + "x" * 450, "absent"]) == (1.0, 0.0)
    with pytest.raises(ValueError):
        reranker.score("x" * 129, ["text"])


def test_fusion_deduplicates_and_carries_citations():
    run = uuid4()

    def row(ordinal):
        return {
            "id": uuid4(),
            "processing_run_id": run,
            "ordinal": ordinal,
            "content": "Synthetic evidence",
            "distance": 0.3,
            "source_metadata": {"page_numbers": [2]},
            "heading_path": ["Term"],
        }

    a, b, c = row(0), row(1), row(2)
    hits = fuse_candidates([a, b, c], [c, c, b], limit=5)
    assert hits[0].chunk_id == c["id"]
    assert len(hits) == 3
    assert hits[0].page_numbers == (2,)
    assert hits[0].heading_path == ("Term",)
    assert all(h.processing_run_id == run for h in hits)


@pytest.mark.asyncio
async def test_reranking_preserves_scope_citations_and_unverified_status():
    scope = object()
    run = uuid4()
    rows = [
        {
            "id": uuid4(),
            "processing_run_id": run,
            "ordinal": i,
            "content": f"Passage {i}",
            "distance": 0.2,
            "source_metadata": {"page_numbers": [i + 1]},
            "heading_path": ["Term"],
        }
        for i in range(2)
    ]
    repository = SimpleNamespace(active_search_candidates=AsyncMock(return_value=(rows, rows)))
    provider = SimpleNamespace(embed_query=lambda _: (1.0,))

    class Reranker:
        def score(self, query, passages):
            assert query == "Missing answer?"
            assert passages == ["Term\nPassage 0", "Term\nPassage 1"]
            return (-10.0, -9.0)

    hits = await HybridRetriever(repository, provider, reranker=Reranker()).search(
        scope, "Missing answer?"
    )
    assert [hit.ordinal for hit in hits] == [1, 0]
    assert hits[0].page_numbers == (2,)
    assert all(hit.evidence_status == "unverified_candidate" for hit in hits)
    assert all(hit.reranker_score < 0 for hit in hits)
    assert repository.active_search_candidates.await_args.args[0] is scope


@pytest.mark.asyncio
async def test_invalid_reranker_output_fails_closed():
    row = {
        "id": uuid4(),
        "processing_run_id": uuid4(),
        "ordinal": 0,
        "content": "Evidence",
        "distance": 0.2,
        "source_metadata": {},
        "heading_path": [],
    }
    repository = SimpleNamespace(active_search_candidates=AsyncMock(return_value=([row], [])))
    for values in ((), (float("nan"),)):
        retriever = HybridRetriever(
            repository,
            SimpleNamespace(embed_query=lambda _: (1.0,)),
            reranker=SimpleNamespace(score=lambda *_, values=values: values),
        )
        with pytest.raises(ValueError):
            await retriever.search(object(), "term")
