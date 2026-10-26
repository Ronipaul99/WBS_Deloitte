"""Offline PDF quality evaluation; writes artifacts, never database rows or tasks.

Run as a module from backend: python -m scripts.evaluate_native_pdf_quality ...
The private question file is JSON with id, query, split, and expected_regex keys.
An empty expected_regex marks an unanswerable question; scores remain candidates,
not calibrated answer-confidence probabilities.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from uuid import NAMESPACE_OID, uuid4, uuid5

from pypdf import PdfReader

from app.core.config import Settings
from app.services.ingestion.chunk_types import ChunkingPolicy
from app.services.ingestion.chunking import DocumentChunker
from app.services.ingestion.embeddings.fastembed_provider import FastEmbedProvider
from app.services.ingestion.extractors.pdf import PdfExtractor
from app.services.ingestion.query_aliases import expand_alias_terms
from app.services.ingestion.retrieval import fuse_candidates, lexical_terms
from app.services.ingestion.tokenizer import LocalBgeTokenizer
from app.services.ingestion.types import ExtractionLimits


def evaluate_queries(chunks, vectors, questions, provider):
    import numpy as np

    from app.services.ingestion.reranking import get_reranker

    reranker = get_reranker()

    matrix = np.asarray(vectors, dtype=np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    results = []
    for question in questions:
        query_vector = np.asarray(provider.embed_query(question["query"]).values)
        similarities = matrix @ (query_vector / np.linalg.norm(query_vector))
        semantic_order = sorted(range(len(chunks)), key=lambda i: (-similarities[i], i))[:30]
        paths = sorted(
            {tuple(chunk.heading_path) for chunk in chunks if "GLOSSARY" in chunk.heading_path}
        )[:128]
        terms = expand_alias_terms(lexical_terms(question["query"]), paths)
        lexical_scores = []
        for chunk in chunks:
            words = Counter(
                re.findall(r"[^\W_]+", (chunk.content + " " + " ".join(chunk.heading_path)).lower())
            )
            lexical_scores.append(sum(min(words[term], 2) for term in terms))
        lexical_order = sorted(
            (i for i, score in enumerate(lexical_scores) if score),
            key=lambda i: (-lexical_scores[i], i),
        )[:30]

        def record(i, similarities=similarities):
            c = chunks[i]
            return {
                "id": uuid5(NAMESPACE_OID, c.chunk_sha256),
                "processing_run_id": NAMESPACE_OID,
                "ordinal": i,
                "content": c.content,
                "distance": 1 - float(similarities[i]),
                "heading_path": c.heading_path,
                "source_metadata": {"page_numbers": c.page_numbers},
            }

        candidates = fuse_candidates(
            [record(i) for i in semantic_order], [record(i) for i in lexical_order], limit=60
        )
        rerank_started = time.monotonic()
        scores = reranker.score(
            question["query"],
            [" > ".join(hit.heading_path) + "\n" + hit.content for hit in candidates],
        )
        hits = sorted(
            zip(candidates, scores, strict=True),
            key=lambda item: (
                -item[1],
                -item[0].score,
                item[0].ordinal,
            ),
        )[:5]
        hit_ordinals = [item[0].ordinal for item in hits]
        pattern = question.get("expected_regex")
        relevant = [
            i
            for i, chunk in enumerate(chunks)
            if pattern
            and re.search(pattern, chunk.content, re.I | re.S)
            and (
                not question.get("expected_pages")
                or set(chunk.page_numbers) & set(question["expected_pages"])
            )
        ]
        results.append(
            {
                **question,
                "relevant_ordinals": relevant,
                "semantic_top5": semantic_order[:5],
                "hybrid_preview_top5": hit_ordinals,
                "semantic_hit": bool(set(relevant) & set(semantic_order[:5])),
                "hybrid_preview_hit": bool(set(relevant) & set(hit_ordinals)),
                "reranker_scores": [item[1] for item in hits],
                "rerank_seconds": time.monotonic() - rerank_started,
                "top_cosine": float(max(similarities)),
                "relevant_in_candidates": [
                    hit.ordinal for hit in candidates if hit.ordinal in relevant
                ],
                "scope": "offline; lexical preview is not PostgreSQL ts_rank_cd",
            }
        )
        print(
            json.dumps(
                {"question_id": question["id"], "preview_hit": results[-1]["hybrid_preview_hit"]}
            ),
            flush=True,
        )
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--questions", type=Path)
    parser.add_argument("--processing-root", type=Path)
    parser.add_argument("--extract-only", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    if args.processing_root:
        settings = settings.model_copy(
            update={
                "document_processing_temp_root": str(args.processing_root.resolve()),
            }
        )
    root = Path(settings.document_processing_temp_root)
    root.mkdir(parents=True, exist_ok=True)
    workspace = root / str(uuid4())
    workspace.mkdir(mode=0o700)
    began = time.monotonic()
    try:
        source = workspace / "input.pdf"
        shutil.copyfile(args.input, source)
        source.chmod(0o600)
        extraction = PdfExtractor.from_settings(settings).extract(
            source,
            ExtractionLimits.from_settings(settings),
        )
        reader = PdfReader(source)
        coverage = []
        for page_number, page in enumerate(reader.pages, start=1):
            blocks = [b for b in extraction.blocks if b.page_number == page_number]
            removed = [value for b in blocks for value in b.metadata.get("removed_margins", [])]
            plain = "".join(
                b.text.replace(" | ", "") if b.block_type.value == "table_row" else b.text
                for b in blocks
            )

            def chars(value):
                return Counter(c for c in value if not c.isspace())

            coverage.append(chars(page.extract_text() or "") == chars(plain + "".join(removed)))
        report = {
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "extraction": extraction.to_jsonable(),
            "coverage_pages": coverage,
            "removed_margins": [
                value for b in extraction.blocks for value in b.metadata.get("removed_margins", [])
            ],
            "chunk_policy": asdict(ChunkingPolicy.from_settings(settings)),
        }
        if not args.extract_only:
            tokenizer = LocalBgeTokenizer.from_settings(settings)
            chunking = DocumentChunker(
                tokenizer=tokenizer, policy=ChunkingPolicy.from_settings(settings)
            ).chunk(extraction)
            provider = FastEmbedProvider.from_settings(settings, require_read_only=True)
            vectors = provider.embed_documents([chunk.content for chunk in chunking.chunks])
            report.update(
                {
                    "chunking": chunking.to_jsonable(),
                    "vectors": [list(vector.values) for vector in vectors],
                    "model_identity": {
                        "provider": provider.provider_name,
                        "model": provider.model_name,
                        "revision": provider.model_revision,
                        "formatting_version": provider.formatting_version,
                    },
                    "tokenizer_sha256": settings.embedding_tokenizer_sha256,
                    "manifest_sha256": settings.embedding_model_manifest_sha256,
                }
            )
            if args.questions:
                report["evaluation"] = evaluate_queries(
                    chunking.chunks,
                    report["vectors"],
                    json.loads(args.questions.read_text()),
                    provider,
                )
        report["elapsed_seconds"] = time.monotonic() - began
        try:
            import resource

            report["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        except ImportError:
            report["peak_rss_kib"] = None
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=True), encoding="utf-8")
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "all_pages_covered": all(coverage),
                    "statistics": extraction.statistics.to_jsonable(),
                    "elapsed_seconds": report["elapsed_seconds"],
                }
            ),
            flush=True,
        )
    finally:
        shutil.rmtree(workspace)


if __name__ == "__main__":
    main()
