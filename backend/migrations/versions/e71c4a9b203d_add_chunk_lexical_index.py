"""Index active chunk lexical retrieval.

Revision ID: e71c4a9b203d
Revises: d4e7b2c91a63
"""

from alembic import op

revision = "e71c4a9b203d"
down_revision = "d4e7b2c91a63"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_chunks_lexical ON document_chunks USING gin "
            "(to_tsvector('simple'::regconfig, content || ' ' || heading_path::text))"
        )


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("ix_chunks_lexical", table_name="document_chunks")
