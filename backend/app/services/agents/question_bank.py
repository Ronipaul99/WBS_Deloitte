"""Validated query embeddings and atomic, repeatable question-template seeding."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.summary_questions import RfpQuestionBank
from app.services.ingestion.embeddings.base import EmbeddingProvider, EmbeddingVector
from app.services.ingestion.embeddings.fastembed_provider import FastEmbedProvider

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _string(value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("Question definition contains an invalid string")
    return value


def prepare_question_rows(
    question_set_id: str,
    questions: Sequence[Mapping[str, Any]],
    *,
    provider: EmbeddingProvider,
    manifest_sha256: str,
    query_prefix: str,
) -> list[dict[str, Any]]:
    """Validate everything before inference; embed question text with query formatting."""
    _string(question_set_id, 80)
    if not _IDENTIFIER.fullmatch(question_set_id) or not questions or len(questions) > 100:
        raise ValueError("Invalid question set")
    if not _SHA256.fullmatch(manifest_sha256):
        raise ValueError("A verified embedding manifest digest is required")
    if (
        provider.provider_name != "fastembed"
        or provider.model_name != FastEmbedProvider.model_name
        or provider.dimensions != 384
        or provider.formatting_version != "bge-small-en-v1.5-format-v1"
        or query_prefix != FastEmbedProvider.format_query("")
    ):
        raise ValueError("Question embeddings must use the document retrieval identity")
    rows = []
    seen = set()
    for ordinal, question in enumerate(questions, start=1):
        question_id = _string(question.get("question_id"), 40)
        if not _IDENTIFIER.fullmatch(question_id) or question_id in seen:
            raise ValueError("Question IDs must be unique within a question set")
        seen.add(question_id)
        instructions = question.get("instructions")
        if not isinstance(instructions, list) or not instructions or len(instructions) > 30:
            raise ValueError("Extraction instructions must be a nonempty list")
        instructions = [_string(item, 2000) for item in instructions]
        answer_type = question.get("answer_type")
        if answer_type not in ("structured_summary", "structured_list"):
            raise ValueError("Invalid question answer type")
        content = {
            "ordinal": ordinal,
            "question_id": question_id,
            "category": _string(question.get("category"), 160),
            "question_text": _string(question.get("question"), 10000),
            "extraction_instructions": instructions,
            "answer_type": answer_type,
        }
        digest = hashlib.sha256(
            json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        rows.append(
            {
                **content,
                "question_set_id": question_set_id,
                "content_sha256": digest,
                "embedding_provider": provider.provider_name,
                "embedding_model": provider.model_name,
                "embedding_model_revision": provider.model_revision,
                "embedding_manifest_sha256": manifest_sha256,
                "embedding_dimensions": provider.dimensions,
                "embedding_formatting_version": provider.formatting_version,
                "query_prefix": query_prefix,
            }
        )
    for row in rows:
        vector = provider.embed_query(row["question_text"])
        row["embedding"] = list(EmbeddingVector(vector.values, dimensions=384).values)
        norm = math.sqrt(sum(value * value for value in row["embedding"]))
        if not math.isclose(norm, 1.0, abs_tol=0.001):
            raise ValueError("Question embeddings must have unit norm")
    return rows


async def load_question_set(session: AsyncSession, question_set_id: str) -> list[RfpQuestionBank]:
    """Read a shared template in display order; vectors search scoped document chunks."""
    return list(
        await session.scalars(
            select(RfpQuestionBank)
            .where(RfpQuestionBank.question_set_id == question_set_id)
            .order_by(RfpQuestionBank.ordinal)
        )
    )


async def verify_question_rows(
    session: AsyncSession, rows: Sequence[Mapping[str, Any]]
) -> list[RfpQuestionBank]:
    if not rows or len({row["question_set_id"] for row in rows}) != 1:
        raise ValueError("Expected one nonempty question set")
    stored = await load_question_set(session, rows[0]["question_set_id"])
    if len(stored) != len(rows):
        raise ValueError("Stored question set does not match the expected question count")
    for actual, expected in zip(stored, rows, strict=True):
        for key, value in expected.items():
            if key == "embedding":
                matches = len(actual.embedding) == len(value) and all(
                    math.isclose(float(a), float(b), rel_tol=1e-5, abs_tol=1e-6)
                    for a, b in zip(actual.embedding, value, strict=True)
                )
            else:
                matches = getattr(actual, key) == value
            if not matches:
                raise ValueError(
                    f"Stored {actual.question_id} differs in {key}; use a new question_set_id "
                    "rather than overwriting a versioned template"
                )
    return stored


@dataclass(frozen=True)
class QuestionSeedResult:
    inserted: int
    unchanged: int


async def seed_question_rows(
    session: AsyncSession, rows: Sequence[Mapping[str, Any]]
) -> QuestionSeedResult:
    """Own one atomic transaction; never silently replace an existing template version."""
    if not rows or len({row["question_set_id"] for row in rows}) != 1:
        raise ValueError("Expected one nonempty question set")
    if len({row["question_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate question IDs")
    dialect = session.get_bind().dialect.name
    if dialect not in ("postgresql", "sqlite"):
        raise ValueError("Unsupported question bank database")
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    async with session.begin():
        if dialect == "postgresql":
            # Serialize repeat/concurrent seed jobs for this shared template.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:set_id, 0))"),
                {"set_id": rows[0]["question_set_id"]},
            )
        statement = (
            insert(RfpQuestionBank)
            .values([dict(row) for row in rows])
            .on_conflict_do_nothing(index_elements=["question_set_id", "question_id"])
            .returning(RfpQuestionBank.question_id)
        )
        inserted = len(list((await session.execute(statement)).scalars()))
        await verify_question_rows(session, rows)
    return QuestionSeedResult(inserted=inserted, unchanged=len(rows) - inserted)
