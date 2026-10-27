"""Scoped credential lifecycle and fresh per-attempt authorization; no routes/LLM calls."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.permissions import Permission
from app.models.auth import AuthEvent
from app.models.llm import LlmConnection, LlmCredentialVersion
from app.services.agents.persistence_types import EndpointPolicyRecord
from app.services.agents.scoped_storage import ScopedStorage, StorageAccess
from app.services.llm.credentials import (
    CredentialAudit,
    CredentialBinding,
    CredentialChange,
    CredentialReceipt,
    CredentialStatus,
    EncryptedCredential,
    KeyRing,
    ResolvedCredential,
    decrypt_credential,
    encrypt_credential,
)
from app.services.llm.endpoint_policy import EndpointRegistry, PinnedEndpoint, Purpose
from app.services.llm.errors import LlmSecurityError, SecurityCode


class CredentialService:
    def __init__(
        self, sessions, access: StorageAccess, keys: KeyRing | None, endpoints: EndpointRegistry
    ):
        self._sessions = sessions
        self._access = access
        self._keys = keys
        self._endpoints = endpoints

    async def _connection(self, session, connection_id, permission):
        await ScopedStorage(session, self._access).authorize(permission)
        row = await session.scalar(
            select(LlmConnection)
            .where(
                LlmConnection.id == connection_id, LlmConnection.tenant_id == self._access.tenant_id
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise LlmSecurityError(SecurityCode.ACCESS_DENIED)
        return row

    async def _active(self, session, connection):
        if connection.active_credential_id is None:
            return None
        row = await session.scalar(
            select(LlmCredentialVersion)
            .where(
                LlmCredentialVersion.id == connection.active_credential_id,
                LlmCredentialVersion.tenant_id == connection.tenant_id,
                LlmCredentialVersion.connection_id == connection.id,
            )
            .execution_options(populate_existing=True)
        )
        if row is None or row.retired_at is not None:
            raise LlmSecurityError(SecurityCode.CREDENTIAL_UNAVAILABLE)
        return row

    @staticmethod
    def _binding(row):
        return CredentialBinding(row.tenant_id, row.connection_id, row.id, row.version)

    @staticmethod
    def _envelope(row):
        return EncryptedCredential(row.ciphertext, row.nonce, row.key_version)

    def _ring(self):
        if self._keys is None:
            raise LlmSecurityError(SecurityCode.KEY_CONFIGURATION)
        return self._keys

    @staticmethod
    def _status(connection, active):
        return CredentialStatus(
            connection_id=connection.id,
            enabled=connection.enabled,
            configured=active is not None,
            credential_id=active.id if active else None,
            credential_version=active.version if active else None,
            key_version=active.key_version if active else None,
        )

    def _audit(self, session, connection, action, active, event_id=None):
        data = CredentialAudit(
            tenant_id=self._access.tenant_id,
            actor_id=self._access.user_id,
            connection_id=connection.id,
            action=action,
            credential_id=active.id if active else None,
            credential_version=active.version if active else None,
            key_version=active.key_version if active else None,
        )
        session.add(
            AuthEvent(
                id=event_id or uuid4(),
                event_type="llm_" + action,
                success=True,
                user_id=self._access.user_id,
                details=data.model_dump(mode="json"),
            )
        )

    async def update(self, connection_id: UUID, change: CredentialChange) -> CredentialStatus:
        failure = None
        try:
            return await self._update(connection_id, change)
        except PermissionError:
            failure = SecurityCode.ACCESS_DENIED
        except (SQLAlchemyError, ValueError):
            failure = SecurityCode.CREDENTIAL_UNAVAILABLE
        raise LlmSecurityError(failure)

    async def _update(self, connection_id, change):
        async with self._sessions.begin() as session:
            return await self.update_in_transaction(session, connection_id, change)

    async def update_in_transaction(self, session, connection_id, change):
        """Management CAS and credential mutation share the caller's transaction."""
        connection = await self._connection(session, connection_id, Permission.LLM_MANAGE)
        active = await self._active(session, connection)
        previous = active
        now = datetime.now(UTC)
        if change.action in {"replace", "rotate"}:
            if change.action == "rotate":
                if active is None:
                    raise LlmSecurityError(SecurityCode.CREDENTIAL_UNAVAILABLE)
                secret = decrypt_credential(
                    self._ring(), self._binding(active), self._envelope(active)
                )
            else:
                secret = change.secret
            version = (
                await session.scalar(
                    select(func.max(LlmCredentialVersion.version)).where(
                        LlmCredentialVersion.connection_id == connection.id,
                        LlmCredentialVersion.tenant_id == self._access.tenant_id,
                    )
                )
                or 0
            ) + 1
            identity = uuid4()
            encrypted = encrypt_credential(
                self._ring(),
                CredentialBinding(self._access.tenant_id, connection.id, identity, version),
                secret,
            )
            active = LlmCredentialVersion(
                id=identity,
                tenant_id=self._access.tenant_id,
                connection_id=connection.id,
                version=version,
                ciphertext=encrypted.ciphertext,
                nonce=encrypted.nonce,
                key_version=encrypted.key_version,
            )
            session.add(active)
            await session.flush()
            connection.active_credential_id = active.id
            if previous is not None:
                previous.retired_at = now
        elif change.action == "clear":
            connection.active_credential_id = None
            connection.enabled = False
            if active is not None:
                active.retired_at = now
            active = None
        elif change.action == "disable":
            connection.enabled = False
        # preserve is deliberately independent of key availability.
        self._audit(session, connection, change.action, active or previous)
        await session.flush()
        return self._status(connection, active)

    async def status(self, connection_id):
        result = None
        failure = SecurityCode.ACCESS_DENIED
        try:
            async with self._sessions.begin() as session:
                row = await self._connection(session, connection_id, Permission.LLM_MANAGE)
                result = self._status(row, await self._active(session, row))
        except PermissionError:
            pass
        except (SQLAlchemyError, ValueError):
            failure = SecurityCode.CREDENTIAL_UNAVAILABLE
        if result is None:
            raise LlmSecurityError(failure)
        return result

    async def prepare(
        self, connection_id: UUID, pinned: PinnedEndpoint, purpose: Purpose
    ) -> ResolvedCredential:
        failure = None
        try:
            async with self._sessions.begin() as session:
                row = await self._connection(session, connection_id, Permission.LLM_USE)
                active = await self._authorized_current(session, row, pinned, purpose)
                secret = decrypt_credential(
                    self._ring(), self._binding(active), self._envelope(active)
                )
                receipt = CredentialReceipt(
                    attempt_id=uuid4(),
                    tenant_id=self._access.tenant_id,
                    actor_id=self._access.user_id,
                    connection_id=row.id,
                    credential_id=active.id,
                    credential_version=active.version,
                    key_version=active.key_version,
                    endpoint_approval_id=pinned.approval.approval_id,
                    purpose=purpose,
                )
                self._audit(session, row, "call_authorized", active, receipt.attempt_id)
                return ResolvedCredential(receipt, secret)
        except PermissionError:
            failure = SecurityCode.ACCESS_DENIED
        except (SQLAlchemyError, ValueError):
            failure = SecurityCode.CREDENTIAL_UNAVAILABLE
        raise LlmSecurityError(failure)

    async def _authorized_current(self, session, row, pinned, purpose):
        if not row.enabled:
            raise LlmSecurityError(SecurityCode.CONNECTION_DISABLED)
        current = self._endpoints.pin(EndpointPolicyRecord.model_validate(row.endpoint_policy))
        if current != pinned:
            raise LlmSecurityError(SecurityCode.ENDPOINT_DENIED)
        self._endpoints.validate(pinned, pinned.base_url + pinned.approval.path_prefix, purpose)
        active = await self._active(session, row)
        if active is None:
            raise LlmSecurityError(SecurityCode.CREDENTIAL_UNAVAILABLE)
        return active

    async def verify(self, receipt: CredentialReceipt, pinned: PinnedEndpoint) -> None:
        """Recheck immediately before writes, using a fresh transaction, never cached ORM state."""
        if (
            receipt.tenant_id != self._access.tenant_id
            or receipt.actor_id != self._access.user_id
            or receipt.endpoint_approval_id != pinned.approval.approval_id
        ):
            raise LlmSecurityError(SecurityCode.ACCESS_DENIED)
        failure = None
        try:
            async with self._sessions.begin() as session:
                row = await self._connection(session, receipt.connection_id, Permission.LLM_USE)
                active = await self._authorized_current(session, row, pinned, receipt.purpose)
                if (active.id, active.version, active.key_version) != (
                    receipt.credential_id,
                    receipt.credential_version,
                    receipt.key_version,
                ):
                    raise LlmSecurityError(SecurityCode.CREDENTIAL_CHANGED)
                return
        except PermissionError:
            failure = SecurityCode.ACCESS_DENIED
        except (SQLAlchemyError, ValueError):
            failure = SecurityCode.CREDENTIAL_UNAVAILABLE
        raise LlmSecurityError(failure)
