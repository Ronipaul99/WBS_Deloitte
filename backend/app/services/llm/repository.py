"""Scoped storage primitives. No provider calls, encryption, or credential API."""

from uuid import UUID

from sqlalchemy import select

from app.core.permissions import Permission
from app.models.llm import (
    LlmConnection,
    LlmCredentialVersion,
    LlmModelProfile,
    LlmModelProfileVersion,
)
from app.services.agents.scoped_storage import ScopedStorage


class LlmRepository(ScopedStorage):
    async def add(self, record):
        if not isinstance(
            record, (LlmConnection, LlmCredentialVersion, LlmModelProfile, LlmModelProfileVersion)
        ):
            raise TypeError("unsupported model record")
        await self.authorize(Permission.LLM_MANAGE)
        self.check_tenant(record)
        self.session.add(record)
        await self.session.flush()
        return record

    async def connection(self, connection_id: UUID):
        await self.authorize(Permission.LLM_MANAGE)
        return await self.session.scalar(
            select(LlmConnection).where(
                LlmConnection.id == connection_id, LlmConnection.tenant_id == self.access.tenant_id
            )
        )

    async def credential_version(self, connection_id: UUID, version_id: UUID):
        # Returns ciphertext only to an authorized backend caller; never a browser DTO.
        await self.authorize(Permission.LLM_MANAGE)
        return await self.session.scalar(
            select(LlmCredentialVersion).where(
                LlmCredentialVersion.id == version_id,
                LlmCredentialVersion.connection_id == connection_id,
                LlmCredentialVersion.tenant_id == self.access.tenant_id,
            )
        )

    async def approved_profiles(self):
        await self.authorize(Permission.LLM_USE)
        return (
            await self.session.scalars(
                select(LlmModelProfileVersion)
                .join(
                    LlmModelProfile,
                    (LlmModelProfile.active_version_id == LlmModelProfileVersion.id)
                    & (LlmModelProfile.tenant_id == LlmModelProfileVersion.tenant_id)
                    & (LlmModelProfile.id == LlmModelProfileVersion.profile_id)
                    & (LlmModelProfile.connection_id == LlmModelProfileVersion.connection_id),
                )
                .join(
                    LlmConnection,
                    (LlmConnection.id == LlmModelProfile.connection_id)
                    & (LlmConnection.tenant_id == LlmModelProfile.tenant_id),
                )
                .where(
                    LlmModelProfileVersion.tenant_id == self.access.tenant_id,
                    LlmModelProfile.enabled.is_(True),
                    LlmConnection.enabled.is_(True),
                    LlmModelProfileVersion.snapshot["capabilities"]["qualification"].as_string()
                    == "live_worker",
                )
            )
        ).all()
