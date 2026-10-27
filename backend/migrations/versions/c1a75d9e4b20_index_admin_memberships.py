"""index administrator memberships

Revision ID: c1a75d9e4b20
Revises: 8c2f6e441b7a
Create Date: 2026-10-22 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c1a75d9e4b20"
down_revision: str | None = "8c2f6e441b7a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_tenant_memberships_role_tenant_user",
        "tenant_memberships",
        ["role", "tenant_id", "user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tenant_memberships_role_tenant_user",
        table_name="tenant_memberships",
    )
