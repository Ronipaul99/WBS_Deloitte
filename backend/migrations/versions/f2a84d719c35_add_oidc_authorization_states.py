"""add oidc authorization states

Revision ID: f2a84d719c35
Revises: e6b91f2c4a73
Create Date: 2026-10-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a84d719c35"
down_revision: str | None = "e6b91f2c4a73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_auth_identity_user_provider",
        "auth_identities",
        ["user_id", "provider"],
        unique=True,
    )
    op.create_table(
        "oidc_authorization_states",
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("return_path", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_oidc_authorization_states_state_hash",
        "oidc_authorization_states",
        ["state_hash"],
        unique=True,
    )
    op.create_index(
        "ix_oidc_authorization_states_expiry",
        "oidc_authorization_states",
        ["expires_at", "consumed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_oidc_authorization_states_expiry", table_name="oidc_authorization_states")
    op.drop_index(
        "ix_oidc_authorization_states_state_hash",
        table_name="oidc_authorization_states",
    )
    op.drop_table("oidc_authorization_states")
    op.drop_index("uq_auth_identity_user_provider", table_name="auth_identities")
