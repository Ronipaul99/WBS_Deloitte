"""Question formatting, version isolation and transaction integrity."""

import copy
import importlib.util
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from pgvector.sqlalchemy import Vector
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.summary_questions import RfpQuestionBank
from app.services.agents.question_bank import (
    load_question_set,
    prepare_question_rows,
    seed_question_rows,
)
from app.services.ingestion.embeddings.base import EmbeddingVector
from app.services.ingestion.embeddings.fastembed_provider import FastEmbedProvider
from migrations.versions import a13d9e7b602c_add_summary_question_bank as migration

SOURCE = Path(__file__).resolve().parents[2] / "question_doc" / "question_bank.py"
spec = importlib.util.spec_from_file_location("source_questions", SOURCE)
bank = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bank)


class Provider:
    provider_name = "fastembed"
    model_name = "BAAI/bge-small-en-v1.5"
    model_revision = "a" * 40
    dimensions = 384
    formatting_version = "bge-small-en-v1.5-format-v1"

    def __init__(self):
        self.queries = []

    def embed_query(self, question):
        self.queries.append(question)
        return EmbeddingVector([1.0] + [0.0] * 383, dimensions=384)


def prepared(*, questions=None, provider=None, set_id=bank.QUESTION_SET_ID):
    return prepare_question_rows(
        set_id,
        bank.QUESTIONS if questions is None else questions,
        provider=provider or Provider(),
        manifest_sha256="b" * 64,
        query_prefix=bank.QUERY_PREFIX,
    )


def test_all_seven_questions_use_query_embedding_and_preserve_instructions():
    provider = Provider()
    rows = prepared(provider=provider)
    assert len(rows) == 7
    assert [row["question_id"] for row in rows] == [f"Q{i:03}" for i in range(1, 8)]
    assert provider.queries == [question["question"] for question in bank.QUESTIONS]
    assert all(row["query_prefix"] == FastEmbedProvider.format_query("") for row in rows)
    assert rows[0]["extraction_instructions"] == bank.QUESTIONS[0]["instructions"]


@pytest.mark.parametrize("invalid", ["duplicate", "instructions", "empty"])
def test_invalid_bank_is_rejected_before_any_embedding(invalid):
    questions = copy.deepcopy(bank.QUESTIONS)
    if invalid == "duplicate":
        questions[-1]["question_id"] = questions[0]["question_id"]
    elif invalid == "instructions":
        questions[-1]["instructions"] = "not a list"
    else:
        questions = []
    provider = Provider()
    with pytest.raises(ValueError):
        prepared(questions=questions, provider=provider)
    assert provider.queries == []


def test_wrong_embedding_identity_and_non_unit_vector_fail():
    provider = Provider()
    provider.model_name = "different-model"
    with pytest.raises(ValueError, match="retrieval identity"):
        prepared(provider=provider)
    provider.model_name = Provider.model_name
    provider.embed_query = lambda _: EmbeddingVector([0.0] * 384, dimensions=384)
    with pytest.raises(ValueError, match="unit norm"):
        prepared(provider=provider)


@pytest.fixture
async def database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    def create_question_table(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

    async with engine.begin() as connection:
        await connection.run_sync(create_question_table)
    yield engine
    await engine.dispose()


def test_question_bank_branch_can_deploy_without_pending_agent_migrations():
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["e53c7a19b402"]
    revisions = list(script.iterate_revisions("a13d9e7b602c", "e71c4a9b203d"))
    assert [revision.revision for revision in revisions] == ["a13d9e7b602c"]
    vector_type = RfpQuestionBank.__table__.c.embedding.type.dialect_impl(postgresql.dialect())
    assert isinstance(vector_type, Vector)
    assert vector_type.dim == 384


async def test_repeat_seed_is_idempotent_and_sets_can_reuse_question_ids(database):
    async with AsyncSession(database) as session:
        first = await seed_question_rows(session, prepared())
        second = await seed_question_rows(session, prepared())
        third = await seed_question_rows(session, prepared(set_id="GENERAL_RFP_V2"))
        assert (first.inserted, first.unchanged) == (7, 0)
        assert (second.inserted, second.unchanged) == (0, 7)
        assert third.inserted == 7
        stored = await load_question_set(session, bank.QUESTION_SET_ID)
        assert [row.ordinal for row in stored] == list(range(1, 8))


async def test_changed_existing_template_rolls_back_new_rows(database):
    rows = prepared()
    async with AsyncSession(database) as session:
        await seed_question_rows(session, rows[:1])
        changed = copy.deepcopy(rows)
        changed[0]["question_text"] = "A changed question must use a new version"
        with pytest.raises(ValueError, match="new question_set_id"):
            await seed_question_rows(session, changed)
        stored = list(await session.scalars(select(RfpQuestionBank)))
        assert len(stored) == 1
        assert stored[0].question_text == rows[0]["question_text"]


async def test_changed_model_revision_cannot_silently_replace_vectors(database):
    async with AsyncSession(database) as session:
        await seed_question_rows(session, prepared())
        provider = Provider()
        provider.model_revision = "c" * 40
        with pytest.raises(ValueError, match="embedding_model_revision"):
            await seed_question_rows(session, prepared(provider=provider))
