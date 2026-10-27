"""Scoped management transactions. No HTTP, provider execution or document access."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select

from app.core.permissions import Permission
from app.models.auth import AuthEvent
from app.models.domain import Job
from app.models.llm import (
    LlmConnection,
    LlmConnectionTest,
    LlmModelProfile,
    LlmModelProfileVersion,
)
from app.schemas.llm import ProfileSettings
from app.services.agents.persistence_types import EndpointPolicyRecord
from app.services.agents.scoped_storage import ScopedStorage
from app.services.llm.adapter_types import fingerprint
from app.services.llm.capabilities import LiveProbePermit
from app.services.llm.contracts import ModelProfileSnapshot, ProviderCapabilities
from app.services.llm.credential_service import CredentialService
from app.services.llm.errors import LlmSecurityError
from app.services.llm.management_types import ManagementError, TestConfiguration, TestLedger

PROTOCOLS = {
    "openai": "responses",
    "anthropic": "anthropic_messages",
    "openai_compatible": "chat_completions",
}
AUTH = {
    "openai": {"bearer"},
    "anthropic": {"anthropic_api_key"},
    "openai_compatible": {"bearer", "gateway_api_key"},
}


class ModelManagement:
    def __init__(
        self, sessions, access, endpoints, keys=None, *, permits=None, tests_enabled=False, now=None
    ):
        self.sessions, self.access, self.endpoints, self.keys = sessions, access, endpoints, keys
        self.permits, self.tests_enabled = permits or {}, tests_enabled
        self.now = now or (lambda: datetime.now(UTC))

    async def authorize(self, session, permission=Permission.LLM_MANAGE):
        await ScopedStorage(session, self.access).authorize(permission)

    def audit(self, session, action, identity):
        session.add(
            AuthEvent(
                id=uuid4(),
                event_type="llm_management_" + action,
                success=True,
                user_id=self.access.user_id,
                details={"tenant_id": str(self.access.tenant_id), "resource_id": str(identity)},
            )
        )

    async def connection(self, session, identity, *, locked=False):
        query = select(LlmConnection).where(
            LlmConnection.id == identity, LlmConnection.tenant_id == self.access.tenant_id
        )
        row = await session.scalar(query.with_for_update() if locked else query)
        if row is None:
            raise ManagementError("llm_not_found", 404)
        return row

    async def profile(self, session, identity, *, locked=False):
        query = select(LlmModelProfile).where(
            LlmModelProfile.id == identity, LlmModelProfile.tenant_id == self.access.tenant_id
        )
        row = await session.scalar(query.with_for_update() if locked else query)
        if row is None:
            raise ManagementError("llm_not_found", 404)
        return row

    @staticmethod
    def cas(row, expected):
        if row.revision != expected:
            raise ManagementError("llm_stale_revision", 409)

    def endpoint(self, approval_id, provider):
        for item in self.endpoints.approved_endpoints():
            if item.approval_id == approval_id and item.auth_scheme in AUTH[provider]:
                return EndpointPolicyRecord(
                    host=item.host,
                    port=item.port,
                    path_prefix=item.path_prefix,
                    approval_id=item.approval_id,
                )
        raise ManagementError("llm_endpoint_unapproved", 422)

    def public_connection(self, row):
        return {
            "id": str(row.id),
            "name": row.name,
            "provider": row.provider,
            "protocol": row.protocol,
            "revision": row.revision,
            "enabled": row.enabled,
            "configured": row.active_credential_id is not None,
            "endpoint": row.endpoint_policy,
        }

    async def invalidate(self, session, connection_id):
        profiles = (
            await session.scalars(
                select(LlmModelProfile)
                .where(
                    LlmModelProfile.tenant_id == self.access.tenant_id,
                    LlmModelProfile.connection_id == connection_id,
                )
                .with_for_update()
            )
        ).all()
        for profile in profiles:
            profile.enabled = profile.is_default = False
            profile.revision += 1

    async def connections(self):
        async with self.sessions.begin() as session:
            await self.authorize(session)
            rows = (
                await session.scalars(
                    select(LlmConnection)
                    .where(LlmConnection.tenant_id == self.access.tenant_id)
                    .order_by(LlmConnection.id)
                    .limit(100)
                )
            ).all()
            return [self.public_connection(r) for r in rows]

    async def save_connection(self, payload, identity=None):
        async with self.sessions.begin() as session:
            await self.authorize(session)
            if identity is None:
                row = LlmConnection(
                    id=uuid4(),
                    tenant_id=self.access.tenant_id,
                    name=payload.name,
                    provider=payload.provider,
                    protocol=PROTOCOLS[payload.provider],
                    endpoint_policy=self.endpoint(payload.approval_id, payload.provider).model_dump(
                        mode="json"
                    ),
                    enabled=False,
                    revision=1,
                )
                session.add(row)
                await session.flush()
            else:
                row = await self.connection(session, identity, locked=True)
                self.cas(row, payload.expected_revision)
                row.revision += 1
                if payload.name is not None:
                    row.name = payload.name
                if payload.approval_id is not None:
                    row.endpoint_policy = self.endpoint(payload.approval_id, row.provider)
                if not isinstance(row.endpoint_policy, dict):
                    row.endpoint_policy = row.endpoint_policy.model_dump(mode="json")
                await self.invalidate(session, row.id)
            credentials = CredentialService(self.sessions, self.access, self.keys, self.endpoints)
            await credentials.update_in_transaction(session, row.id, payload.credential)
            if payload.enabled is not None:
                row.enabled = payload.enabled
            if payload.credential.action in {"clear", "disable"}:
                row.enabled = False
            if row.enabled and row.active_credential_id is None:
                raise ManagementError("llm_credential_required", 422)
            self.audit(session, "connection_saved", row.id)
            await session.flush()
            return self.public_connection(row)

    async def credential(self, identity, payload):
        async with self.sessions.begin() as session:
            await self.authorize(session)
            row = await self.connection(session, identity, locked=True)
            self.cas(row, payload.expected_revision)
            await CredentialService(
                self.sessions, self.access, self.keys, self.endpoints
            ).update_in_transaction(session, identity, payload.change)
            row.revision += 1
            await self.invalidate(session, identity)
            await session.flush()
            return self.public_connection(row)

    async def version(self, session, profile):
        query = select(LlmModelProfileVersion).where(
            LlmModelProfileVersion.profile_id == profile.id,
            LlmModelProfileVersion.connection_id == profile.connection_id,
            LlmModelProfileVersion.tenant_id == self.access.tenant_id,
        )
        if profile.active_version_id is not None:
            query = query.where(LlmModelProfileVersion.id == profile.active_version_id)
        row = await session.scalar(query.order_by(LlmModelProfileVersion.version.desc()).limit(1))
        if row is None:
            raise ManagementError("llm_profile_unavailable", 409)
        return row

    async def public_profile(self, session, profile, *, catalog=False):
        version = await self.version(session, profile)
        connection = await self.connection(session, profile.connection_id)
        snapshot = ModelProfileSnapshot.model_validate(version.snapshot)
        qualified = await self.usable(session, profile, version, connection)
        if not connection.enabled:
            availability = "disabled"
        elif snapshot.capabilities.qualification == "pending":
            availability = "unverified"
        elif not qualified:
            availability = "stale"
        else:
            availability = "usable" if profile.enabled else "disabled"
        data = {
            "id": str(profile.id),
            "name": profile.name,
            "connection_id": str(connection.id),
            "revision": profile.revision,
            "version": version.version,
            "model_id": snapshot.model_id,
            "provider": connection.provider,
            "enabled": profile.enabled,
            "is_default": profile.is_default,
            "usable": qualified and profile.enabled,
            "availability": availability,
            "qualification": snapshot.capabilities.qualification,
            "tested_at": snapshot.capabilities.tested_at,
            "settings": version.settings,
            "capabilities": snapshot.capabilities.model_dump(mode="json"),
        }
        if not catalog:
            try:
                data["candidate_fingerprint"] = fingerprint(
                    snapshot,
                    self.endpoints.pin(
                        EndpointPolicyRecord.model_validate(connection.endpoint_policy)
                    ),
                    ProfileSettings.model_validate(version.settings).options,
                    include_capabilities=False,
                )
            except LlmSecurityError:
                data["candidate_fingerprint"] = None
        return data

    async def usable(self, session, profile, version, connection):
        if self.keys is None:
            return False
        try:
            self.endpoints.pin(EndpointPolicyRecord.model_validate(connection.endpoint_policy))
        except LlmSecurityError:
            return False
        if (
            not connection.enabled
            or connection.active_credential_id is None
            or not version.qualification_test_id
        ):
            return False
        test = await session.scalar(
            select(LlmConnectionTest).where(
                LlmConnectionTest.id == version.qualification_test_id,
                LlmConnectionTest.tenant_id == self.access.tenant_id,
                LlmConnectionTest.connection_id == connection.id,
                LlmConnectionTest.profile_id == profile.id,
            )
        )
        if test is not None:
            config = TestConfiguration.model_validate(test.configuration)
            try:
                current_pin = self.endpoints.pin(config.endpoint)
            except LlmSecurityError:
                return False
            if fingerprint(
                config.profile, current_pin, config.settings.options, include_capabilities=False
            ) != config.fingerprint or version.settings != config.settings.model_dump(mode="json"):
                return False
        return bool(
            test
            and test.state == "succeeded"
            and test.result.get("origin") == "live_worker"
            and test.result.get("qualified_version_id") == str(version.id)
            and test.configuration["connection_revision"] == connection.revision
            and version.snapshot["capabilities"]["qualification"] == "live_worker"
        )

    async def profiles(self, *, catalog=False):
        async with self.sessions.begin() as session:
            await self.authorize(session, Permission.LLM_USE if catalog else Permission.LLM_MANAGE)
            rows = (
                await session.scalars(
                    select(LlmModelProfile)
                    .where(LlmModelProfile.tenant_id == self.access.tenant_id)
                    .order_by(LlmModelProfile.id)
                    .limit(100)
                )
            ).all()
            results = [await self.public_profile(session, p, catalog=catalog) for p in rows]
            return [r for r in results if r["usable"]] if catalog else results

    async def save_profile(self, payload, identity=None):
        async with self.sessions.begin() as session:
            await self.authorize(session)
            if identity is None:
                connection = await self.connection(session, payload.connection_id, locked=True)
                profile = LlmModelProfile(
                    id=uuid4(),
                    tenant_id=self.access.tenant_id,
                    connection_id=connection.id,
                    name=payload.name,
                    revision=1,
                    enabled=False,
                    is_default=False,
                )
                session.add(profile)
                await session.flush()
            else:
                profile = await self.profile(session, identity, locked=True)
                self.cas(profile, payload.expected_revision)
                connection = await self.connection(session, profile.connection_id)
                profile.revision += 1
                profile.enabled = profile.is_default = False
                profile.name = payload.name
            settings = payload.settings
            if identity is not None:
                previous = await self.version(session, profile)
                caps = ModelProfileSnapshot.model_validate(previous.snapshot).capabilities
                if (
                    settings.temperature is not None
                    and caps.temperature == "unsupported"
                    or settings.tool_mode == "native"
                    and caps.native_tools == "unsupported"
                    or settings.output_mode == "native_json_schema"
                    and caps.json_schema == "unsupported"
                ):
                    raise ManagementError("llm_unsupported_setting", 422)
            if (
                connection.provider != "openai_compatible"
                and settings.options.compatible_token_parameter != "max_tokens"
            ):
                raise ManagementError("llm_unsupported_setting", 422)
            number = (
                await session.scalar(
                    select(func.max(LlmModelProfileVersion.version)).where(
                        LlmModelProfileVersion.tenant_id == self.access.tenant_id,
                        LlmModelProfileVersion.profile_id == profile.id,
                    )
                )
                or 0
            ) + 1
            snapshot = ModelProfileSnapshot(
                tenant_id=self.access.tenant_id,
                connection_id=connection.id,
                profile_id=profile.id,
                profile_version=number,
                provider=connection.provider,
                protocol=connection.protocol,
                model_id=payload.model_id,
                capabilities=ProviderCapabilities(),
                timeout_seconds=settings.timeout_seconds,
                max_calls=settings.max_calls,
                max_total_tokens=settings.max_total_tokens,
            )
            version = LlmModelProfileVersion(
                id=uuid4(),
                tenant_id=self.access.tenant_id,
                connection_id=connection.id,
                profile_id=profile.id,
                version=number,
                snapshot=snapshot.model_dump(mode="json"),
                settings=settings.model_dump(mode="json"),
            )
            session.add(version)
            await session.flush()
            profile.active_version_id = version.id
            self.audit(session, "profile_saved", profile.id)
            await session.flush()
            return await self.public_profile(session, profile)

    async def set_profile_state(self, identity, payload):
        async with self.sessions.begin() as session:
            await self.authorize(session)
            # Serialize defaults and connection mutation within a tenant.
            from app.models.domain import Tenant

            await session.scalar(
                select(Tenant).where(Tenant.id == self.access.tenant_id).with_for_update()
            )
            hint = await self.profile(session, identity)
            connection = await self.connection(session, hint.connection_id, locked=True)
            profile = await self.profile(session, identity, locked=True)
            self.cas(profile, payload.expected_revision)
            version = await self.version(session, profile)
            if payload.enabled and not await self.usable(session, profile, version, connection):
                raise ManagementError("llm_qualification_required", 409)
            if payload.is_default:
                defaults = (
                    await session.scalars(
                        select(LlmModelProfile)
                        .where(
                            LlmModelProfile.tenant_id == self.access.tenant_id,
                            LlmModelProfile.is_default.is_(True),
                        )
                        .with_for_update()
                    )
                ).all()
                for old in defaults:
                    old.is_default = False
                    old.revision += 1
                await session.flush()
            profile.enabled, profile.is_default = payload.enabled, payload.is_default
            profile.revision += 1
            self.audit(session, "profile_state", profile.id)
            await session.flush()
            return await self.public_profile(session, profile)

    async def submit_test(self, connection_id, payload):
        if not self.tests_enabled:
            raise ManagementError("llm_tests_disabled")
        async with self.sessions.begin() as session:
            await self.authorize(session)
            connection = await self.connection(session, connection_id, locked=True)
            active_tests = await session.scalar(
                select(func.count())
                .select_from(LlmConnectionTest)
                .where(
                    LlmConnectionTest.tenant_id == self.access.tenant_id,
                    LlmConnectionTest.connection_id == connection_id,
                    LlmConnectionTest.state.in_(("queued", "running")),
                )
            )
            if active_tests >= 1:
                raise ManagementError("llm_test_already_pending", 409)
            profile = await self.profile(session, payload.profile_id, locked=True)
            self.cas(connection, payload.expected_connection_revision)
            self.cas(profile, payload.expected_profile_revision)
            if profile.connection_id != connection.id:
                raise ManagementError("llm_not_found", 404)
            if not connection.enabled or connection.active_credential_id is None:
                raise ManagementError("llm_connection_unavailable", 409)
            version = await self.version(session, profile)
            snapshot = ModelProfileSnapshot.model_validate(version.snapshot)
            settings = ProfileSettings.model_validate(version.settings)
            if (
                payload.plan.input_token_ceiling + payload.plan.max_output_tokens
                > settings.context_tokens
                or payload.plan.max_output_tokens > settings.output_tokens
            ):
                raise ManagementError("llm_probe_limits_invalid", 422)
            pinned = self.endpoints.pin(
                EndpointPolicyRecord.model_validate(connection.endpoint_policy)
            )
            fp = fingerprint(snapshot, pinned, settings.options, include_capabilities=False)
            permit_data = self.permits.get(fp)
            if not permit_data:
                raise ManagementError("llm_test_authorization_required")
            permit = LiveProbePermit.model_validate(permit_data)
            if (
                permit.connection_id != connection.id
                or permit.configuration_fingerprint != fp
                or permit.expires_at <= self.now()
            ):
                raise ManagementError("llm_test_authorization_required")
            identity = uuid4()
            config = TestConfiguration(
                operation=payload.operation,
                profile=snapshot,
                settings=settings,
                endpoint=connection.endpoint_policy,
                connection_revision=connection.revision,
                profile_revision=profile.revision,
                fingerprint=fp,
                plan=payload.plan,
                permit=permit,
            )
            session.add(
                Job(
                    id=identity,
                    tenant_id=self.access.tenant_id,
                    created_by=self.access.user_id,
                    job_type="LLM_CONNECTION_TEST",
                    status="QUEUED",
                    request_payload={"llm_test_id": str(identity)},
                    result_payload={},
                )
            )
            await session.flush()
            record = LlmConnectionTest(
                id=identity,
                tenant_id=self.access.tenant_id,
                connection_id=connection.id,
                profile_id=profile.id,
                profile_version_id=version.id,
                requested_by=self.access.user_id,
                configuration=config.model_dump(mode="json"),
                ledger=TestLedger(
                    deadline=min(permit.expires_at, self.now() + timedelta(seconds=60))
                ).model_dump(mode="json"),
                result={},
                state="queued",
                delivery_state="pending",
                fence=0,
                delivery_fence=0,
                delivery_attempts=0,
                available_at=self.now(),
            )
            session.add(record)
            self.audit(session, "test_queued", identity)
            await session.flush()
            return self.public_test(record)

    @staticmethod
    def public_test(row):
        return {
            "id": str(row.id),
            "connection_id": str(row.connection_id),
            "profile_id": str(row.profile_id),
            "state": row.state,
            "error_code": row.error_code,
            "result": row.result,
            "calls_reserved": row.ledger["calls"],
            "tokens_reserved": row.ledger["reserved_tokens"],
        }

    async def get_test(self, connection_id, identity):
        async with self.sessions.begin() as session:
            await self.authorize(session)
            row = await session.scalar(
                select(LlmConnectionTest).where(
                    LlmConnectionTest.id == identity,
                    LlmConnectionTest.connection_id == connection_id,
                    LlmConnectionTest.tenant_id == self.access.tenant_id,
                )
            )
            if row is None:
                raise ManagementError("llm_not_found", 404)
            return self.public_test(row)


def operator_json(secret):
    try:
        raw = secret.get_secret_value() if secret is not None else "{}"
        if len(raw.encode()) > 131072:
            raise ValueError()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise ManagementError("llm_operator_configuration_invalid") from None
