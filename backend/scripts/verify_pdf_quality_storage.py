"""Read-only integrity/relevance audit of one active PDF run using runtime credentials.

The private question JSON is the same format as evaluate_native_pdf_quality.py.
Results are candidate relevance, not generated answers or calibrated confidence.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import time
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from app.core.config import Settings
from app.db.session import SessionLocal, engine, set_local_tenant_context
from app.services.ingestion.embeddings.fastembed_provider import FastEmbedProvider
from app.services.ingestion.repository import DocumentScope, VectorPersistenceRepository
from app.services.ingestion.retrieval import HybridRetriever


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", type=UUID, required=True)
    parser.add_argument("--project", type=UUID, required=True)
    parser.add_argument("--document", type=UUID, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous-run", type=UUID)
    parser.add_argument("--candidate-artifact", type=Path)
    parser.add_argument("--minimum-recall", type=float, default=0.85)
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="Skip re-embedding and report reproducibility as unverified in this invocation",
    )
    parser.add_argument(
        "--question-id", action="append", help="Limit a diagnostic invocation to these question IDs"
    )
    args = parser.parse_args()
    if not 0 <= args.minimum_recall <= 1:
        parser.error("--minimum-recall must be between 0 and 1")
    settings = Settings()
    scope = DocumentScope(args.tenant, args.project, args.document)
    started = time.monotonic()
    async with SessionLocal() as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await set_local_tenant_context(session, args.tenant)
        parameters = {"doc": args.document, "project": args.project, "tenant": args.tenant}
        doc = await session.scalar(
            text(
                "SELECT to_jsonb(d) FROM documents d WHERE id=:doc "
                "AND project_id=:project AND tenant_id=:tenant"
            ),
            parameters,
        )
        assert doc and doc["lifecycle_status"] == "ACTIVE"
        run = await session.scalar(
            text("SELECT to_jsonb(r) FROM document_processing_runs r WHERE id=CAST(:run AS uuid)"),
            {"run": doc["current_processing_run_id"]},
        )
        assert run and run["status"] == "COMPLETED"
        rows = list(
            (
                await session.execute(
                    text(
                        "SELECT to_jsonb(c)-'embedding' AS metadata, "
                        "embedding::text AS vector FROM document_chunks c WHERE "
                        "processing_run_id=CAST(:run AS uuid) ORDER BY ordinal"
                    ),
                    {"run": run["id"]},
                )
            ).mappings()
        )
        previous_count = None
        if args.previous_run:
            previous_count = await session.scalar(
                text(
                    "SELECT count(*) FROM document_chunks "
                    "WHERE document_id=:doc AND processing_run_id=:run"
                ),
                {"doc": args.document, "run": args.previous_run},
            )
        await set_local_tenant_context(session, UUID("11111111-1111-1111-1111-111111111111"))
        assert (
            await session.scalar(
                text("SELECT count(*) FROM document_chunks WHERE document_id=:doc"),
                {"doc": args.document},
            )
            == 0
        )
    assert len(rows) == run["chunk_count"] and rows
    assert [row["metadata"]["ordinal"] for row in rows] == list(range(len(rows)))
    assert run["document_content_sha256"] == doc["content_sha256"]
    assert run["embedding_model_revision"] == settings.embedding_model_revision
    source_blocks = set()
    table_rows = set()
    for row in rows:
        chunk = row["metadata"]
        assert all(chunk[k] == doc[k] for k in ("tenant_id", "project_id"))
        assert chunk["document_id"] == doc["id"] and chunk["processing_run_id"] == run["id"]
        assert 0 < chunk["token_count"] <= settings.document_chunk_max_tokens
        references = chunk["source_metadata"]["source_references"]
        assert references and all(
            1 <= ref["page_number"] <= run["page_count"] for ref in references
        )
        source_blocks.update(ref["block_ordinal"] for ref in references if ref["role"] == "primary")
        table_rows.update(
            (ref["table_index"], ref["row_index"])
            for ref in references
            if "table_index" in ref and "row_index" in ref
        )
        payload = {
            "domain": "wbs-canonical-chunk-v1",
            "chunker_version": run["chunker_version"],
            "tokenizer_name": run["embedding_model"],
            "tokenizer_revision": run["embedding_model_revision"],
            "source_content_sha256": run["document_content_sha256"],
            "confirmed_format": "pdf",
            "content": chunk["content"],
            "heading_path": chunk["heading_path"],
            "source_references": references,
        }
        digest = hashlib.sha256(
            json.dumps(
                payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        assert digest == chunk["content_sha256"]
    assert source_blocks == set(range(run["block_count"]))
    candidate_matches = None
    if args.candidate_artifact:
        candidate = json.loads(args.candidate_artifact.read_text())
        assert candidate["source_sha256"] == run["document_content_sha256"]
        assert candidate["chunking"]["chunker_version"] == run["chunker_version"]
        assert [row["metadata"]["content_sha256"] for row in rows] == [
            chunk["chunk_sha256"] for chunk in candidate["chunking"]["chunks"]
        ]
        candidate_matches = True
    print(json.dumps({"active_chunks": len(rows), "canonical_hashes": "passed"}), flush=True)
    provider = FastEmbedProvider.from_settings(settings, require_read_only=True)
    stored = [json.loads(row["vector"]) for row in rows]
    maximum_error = None
    if not args.retrieval_only:
        generated = provider.embed_documents([row["metadata"]["content"] for row in rows])
        assert len(generated) == len(stored)
        maximum_error = max(
            abs(a - b)
            for new, old in zip(generated, stored, strict=True)
            for a, b in zip(new.values, old, strict=True)
        )
        assert maximum_error < 1e-5
    assert all(
        len(v) == 384
        and all(math.isfinite(x) for x in v)
        and abs(math.sqrt(sum(x * x for x in v)) - 1) < 1e-4
        for v in stored
    )
    retriever = HybridRetriever(VectorPersistenceRepository(SessionLocal), provider)
    questions = json.loads(args.questions.read_text())
    if args.question_id:
        assert set(args.question_id) <= {question["id"] for question in questions}
        questions = [question for question in questions if question["id"] in args.question_id]
    evaluations = []
    for question in questions:
        query_started = time.monotonic()
        hits = await retriever.search(scope, question["query"])
        assert all(str(hit.processing_run_id) == run["id"] for hit in hits)
        pattern = question.get("expected_regex")
        relevant = [
            row["metadata"]["ordinal"]
            for row in rows
            if pattern
            and re.search(pattern, row["metadata"]["content"], re.I | re.S)
            and (
                not question.get("expected_pages")
                or set(row["metadata"]["source_metadata"]["page_numbers"])
                & set(question["expected_pages"])
            )
        ]
        evaluations.append(
            {
                **question,
                "relevant_ordinals": relevant,
                "top5": [
                    {
                        "ordinal": hit.ordinal,
                        "pages": hit.page_numbers,
                        "score": hit.score,
                        "cosine_similarity": hit.cosine_similarity,
                        "reranker_score": hit.reranker_score,
                    }
                    for hit in hits
                ],
                "hit": bool(set(relevant) & {hit.ordinal for hit in hits}),
                "evidence_status": "candidate_retrieval_only",
                "retrieval_seconds": time.monotonic() - query_started,
            }
        )
        print(
            json.dumps({"question_id": question["id"], "hit": evaluations[-1]["hit"]}), flush=True
        )
    answerable = [item for item in evaluations if item.get("expected_regex")]
    recall = sum(item["hit"] for item in answerable) / len(answerable) if answerable else None
    report = {
        "run": run,
        "previous_run_chunk_count": previous_count,
        "active_chunk_count": len(rows),
        "vector_component_max_error": maximum_error,
        "offline_candidate_matches": candidate_matches,
        "vector_reembedding_verified": not args.retrieval_only,
        "question_selection": args.question_id or "complete",
        "all_primary_blocks_covered": True,
        "tenant_isolation_passed": True,
        "heading_chunks": sum(bool(row["metadata"]["heading_path"]) for row in rows),
        "table_rows_referenced": len(table_rows),
        "footer_chunks": sum(
            bool(re.search(r"Page \d+ of \d+", row["metadata"]["content"])) for row in rows
        ),
        "recall_at_5": recall,
        "minimum_recall": args.minimum_recall,
        "evaluation": evaluations,
        "elapsed_seconds": time.monotonic() - started,
    }
    try:
        import resource

        report["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except ImportError:
        report["peak_rss_kib"] = None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "recall_at_5": recall,
                "failures": [x["id"] for x in answerable if not x["hit"]],
                "max_vector_error": maximum_error,
            }
        ),
        flush=True,
    )
    assert recall is None or recall >= args.minimum_recall
    assert all(
        item["hit"]
        for item in evaluations
        if item["id"] in {"ppa-years", "ppa-term", "emd-one", "emd-two"}
    )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
