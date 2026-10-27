"""Merge the existing question-bank and document-workflow migration histories.

Revision ID: c92e6b4a710d
Revises: a13d9e7b602c, f31a0d8c72e9

Both branches descend from e71c4a9b203d. Their migrations own separate tables;
the merge itself changes no application tables or data. Keep both original
parent revisions intact so databases on either branch can upgrade normally.
"""

revision = "c92e6b4a710d"
down_revision = ("a13d9e7b602c", "f31a0d8c72e9")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
