"""add vector persistence processing identity

Revision ID: b6e2f719c4d8
Revises: a4f9c2d18e76
Create Date: 2026-10-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6e2f719c4d8"
down_revision: str | None = "a4f9c2d18e76"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IDENTITY_COLUMNS = (
    "document_id",
    "document_content_sha256",
    "extractor_name",
    "extractor_version",
    "chunker_version",
    "embedding_provider",
    "embedding_model",
    "embedding_model_revision",
    "embedding_dimensions",
    "embedding_formatting_version",
)


def upgrade() -> None:
    with op.batch_alter_table("document_processing_runs") as batch_op:
        batch_op.drop_constraint("uq_runs_idempotency", type_="unique")
        batch_op.add_column(sa.Column("chunker_version", sa.String(length=40), nullable=True))
        batch_op.add_column(
            sa.Column("embedding_model_revision", sa.String(length=128), nullable=True)
        )
        batch_op.add_column(
            sa.Column("embedding_formatting_version", sa.String(length=80), nullable=True)
        )
        batch_op.create_unique_constraint("uq_runs_idempotency", list(IDENTITY_COLUMNS))


def _assert_versioned_identity_is_empty() -> None:
    bind = op.get_bind()
    has_versioned_data = bind.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM document_processing_runs "
            "WHERE chunker_version IS NOT NULL "
            "OR embedding_model_revision IS NOT NULL "
            "OR embedding_formatting_version IS NOT NULL)"
        )
    )
    if has_versioned_data:
        raise RuntimeError(
            "Versioned processing identities exist; use a reviewed forward fix instead of downgrade"
        )


def downgrade() -> None:
    _assert_versioned_identity_is_empty()
    with op.batch_alter_table("document_processing_runs") as batch_op:
        batch_op.drop_constraint("uq_runs_idempotency", type_="unique")
        batch_op.drop_column("embedding_formatting_version")
        batch_op.drop_column("embedding_model_revision")
        batch_op.drop_column("chunker_version")
        batch_op.create_unique_constraint(
            "uq_runs_idempotency",
            [
                "document_id",
                "document_content_sha256",
                "extractor_name",
                "extractor_version",
                "embedding_provider",
                "embedding_model",
                "embedding_dimensions",
            ],
        )
