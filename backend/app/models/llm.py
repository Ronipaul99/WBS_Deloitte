"""Scoped connection/profile storage. No encryption or inference implementation."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.agent_types import TenantRecord, bounded_json, json_column


class LlmConnection(UUIDPrimaryKeyMixin, TimestampMixin, TenantRecord, Base):
    __tablename__ = "llm_connections"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_llm_connection_scope"),
        ForeignKeyConstraint(
            ["active_credential_id", "tenant_id", "id"],
            [
                "llm_credential_versions.id",
                "llm_credential_versions.tenant_id",
                "llm_credential_versions.connection_id",
            ],
            name="fk_llm_active_credential",
            use_alter=True,
        ),
        CheckConstraint(
            "(provider = 'openai' AND protocol = 'responses') OR "
            "(provider = 'anthropic' AND protocol = 'anthropic_messages') OR "
            "(provider = 'openai_compatible' AND protocol = 'chat_completions')",
            name="ck_llm_protocol",
        ),
        bounded_json("endpoint_policy", "ck_llm_endpoint_policy_size", 8192),
        Index("ix_llm_connections_tenant", "tenant_id", "enabled"),
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    protocol: Mapped[str] = mapped_column(String(24), nullable=False)
    endpoint_policy: Mapped[dict] = json_column()
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    active_credential_id: Mapped[UUID | None] = mapped_column(nullable=True)


class LlmCredentialVersion(UUIDPrimaryKeyMixin, TimestampMixin, TenantRecord, Base):
    __tablename__ = "llm_credential_versions"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", "connection_id", name="uq_llm_credential_scope"),
        UniqueConstraint("connection_id", "version", name="uq_llm_credential_version"),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["llm_connections.id", "llm_connections.tenant_id"],
            name="fk_llm_credential_connection",
        ),
        CheckConstraint("version > 0", name="ck_llm_credential_version"),
        CheckConstraint("length(ciphertext) BETWEEN 16 AND 16384", name="ck_llm_ciphertext"),
        CheckConstraint("length(nonce) BETWEEN 12 AND 32", name="ck_llm_nonce"),
    )
    connection_id: Mapped[UUID] = mapped_column(nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[str] = mapped_column(String(80), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LlmModelProfile(UUIDPrimaryKeyMixin, TimestampMixin, TenantRecord, Base):
    __tablename__ = "llm_model_profiles"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", "connection_id", name="uq_llm_profile_scope"),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["llm_connections.id", "llm_connections.tenant_id"],
            name="fk_llm_profile_connection",
        ),
        ForeignKeyConstraint(
            ["active_version_id", "tenant_id", "id", "connection_id"],
            [
                "llm_model_profile_versions.id",
                "llm_model_profile_versions.tenant_id",
                "llm_model_profile_versions.profile_id",
                "llm_model_profile_versions.connection_id",
            ],
            name="fk_llm_active_profile_version",
            use_alter=True,
        ),
        Index(
            "uq_llm_default_profile",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default"),
        ),
        CheckConstraint("NOT is_default OR enabled", name="ck_llm_default_enabled"),
        Index("ix_llm_profiles_tenant", "tenant_id", "enabled"),
    )
    connection_id: Mapped[UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    active_version_id: Mapped[UUID | None] = mapped_column(nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)


class LlmModelProfileVersion(UUIDPrimaryKeyMixin, TimestampMixin, TenantRecord, Base):
    __tablename__ = "llm_model_profile_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["qualification_test_id", "tenant_id", "connection_id", "profile_id"],
            [
                "llm_connection_tests.id",
                "llm_connection_tests.tenant_id",
                "llm_connection_tests.connection_id",
                "llm_connection_tests.profile_id",
            ],
            use_alter=True,
            name="fk_profile_qualification_test",
        ),
        UniqueConstraint(
            "id", "tenant_id", "profile_id", "connection_id", name="uq_llm_profile_version_scope"
        ),
        UniqueConstraint("profile_id", "version", name="uq_llm_profile_version"),
        ForeignKeyConstraint(
            ["profile_id", "tenant_id", "connection_id"],
            [
                "llm_model_profiles.id",
                "llm_model_profiles.tenant_id",
                "llm_model_profiles.connection_id",
            ],
            name="fk_llm_version_profile",
        ),
        CheckConstraint("version > 0", name="ck_llm_profile_version"),
        bounded_json("snapshot", "ck_llm_profile_snapshot_size", 16384),
    )
    connection_id: Mapped[UUID] = mapped_column(nullable=False)
    profile_id: Mapped[UUID] = mapped_column(nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = json_column()
    settings: Mapped[dict] = mapped_column(
        json_column().column.type, nullable=False, default=dict, server_default=text("'{}'")
    )
    qualification_test_id: Mapped[UUID | None] = mapped_column(nullable=True)


class LlmConnectionTest(UUIDPrimaryKeyMixin, TimestampMixin, TenantRecord, Base):
    """Document-free test and inline transactional delivery record."""

    __tablename__ = "llm_connection_tests"
    __table_args__ = (
        ForeignKeyConstraint(["id", "tenant_id"], ["jobs.id", "jobs.tenant_id"]),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"], ["llm_connections.id", "llm_connections.tenant_id"]
        ),
        ForeignKeyConstraint(
            ["profile_version_id", "tenant_id", "profile_id", "connection_id"],
            [
                "llm_model_profile_versions.id",
                "llm_model_profile_versions.tenant_id",
                "llm_model_profile_versions.profile_id",
                "llm_model_profile_versions.connection_id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "requested_by"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
        ),
        UniqueConstraint("id", "tenant_id", name="uq_llm_test_scope"),
        UniqueConstraint(
            "id", "tenant_id", "connection_id", "profile_id", name="uq_llm_test_profile_scope"
        ),
        CheckConstraint(
            "state IN ('queued','running','succeeded','failed','unavailable')",
            name="ck_llm_test_state",
        ),
        CheckConstraint(
            "delivery_state IN ('pending','publishing','published','retry','dead')",
            name="ck_llm_test_delivery",
        ),
        CheckConstraint(
            "fence >= 0 AND delivery_fence >= 0 AND delivery_attempts BETWEEN 0 AND 5",
            name="ck_llm_test_counts",
        ),
        Index("ix_llm_tests_delivery", "tenant_id", "state", "available_at"),
    )
    connection_id: Mapped[UUID] = mapped_column(nullable=False)
    profile_id: Mapped[UUID] = mapped_column(nullable=False)
    profile_version_id: Mapped[UUID] = mapped_column(nullable=False)
    requested_by: Mapped[UUID] = mapped_column(nullable=False)
    configuration: Mapped[dict] = json_column()
    ledger: Mapped[dict] = json_column()
    result: Mapped[dict] = mapped_column(json_column().column.type, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    delivery_state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    fence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivery_fence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_lease_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
