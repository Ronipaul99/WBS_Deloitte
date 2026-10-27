"""Shared, non-tenant question templates; application roles have read-only access."""

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, CheckConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class RfpQuestionBank(Base, TimestampMixin):
    __tablename__ = "rfp_question_bank"
    __table_args__ = (
        UniqueConstraint("question_set_id", "ordinal", name="uq_rfp_question_order"),
        CheckConstraint("ordinal > 0", name="ck_rfp_question_ordinal"),
        CheckConstraint("embedding_dimensions = 384", name="ck_rfp_question_dimensions"),
        CheckConstraint(
            "answer_type IN ('structured_summary', 'structured_list')",
            name="ck_rfp_question_answer_type",
        ),
    )

    question_set_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    question_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(160), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_instructions: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    answer_type: Mapped[str] = mapped_column(String(40), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        JSON().with_variant(Vector(384), "postgresql"), nullable=False
    )
    embedding_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(160), nullable=False)
    embedding_model_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_formatting_version: Mapped[str] = mapped_column(String(80), nullable=False)
    query_prefix: Mapped[str] = mapped_column(Text, nullable=False)
