"""Document-free durable test execution; no summary graph or document reader."""

import asyncio
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from app.models.domain import Job
from app.models.llm import LlmConnectionTest, LlmModelProfileVersion
from app.services.agents.storage import aware
from app.services.llm.adapter_types import CallBudget
from app.services.llm.capabilities import CapabilityProber, LiveProbePermit
from app.services.llm.contracts import ModelProfileSnapshot, ProviderCapabilities, Support
from app.services.llm.management_types import ManagementError, TestConfiguration, TestLedger


class TestExecution:
    def __init__(self, management, identity):
        self.management, self.identity = management, identity

    async def terminal(self, session, row, state, code):
        row.state, row.error_code = state, code
        job = await session.get(Job, row.id)
        if job is not None:
            job.status, job.error_code = "FAILED", code
            job.result_payload = {"test_id": str(row.id), "state": state}

    async def row(self, session, *, fence=None, pins=True):
        m = self.management
        await m.authorize(session)
        row = await session.scalar(
            select(LlmConnectionTest)
            .where(
                LlmConnectionTest.id == self.identity,
                LlmConnectionTest.tenant_id == m.access.tenant_id,
                LlmConnectionTest.requested_by == m.access.user_id,
            )
            .with_for_update()
        )
        if row is None:
            raise ManagementError("llm_not_found", 404)
        if fence is not None and (
            row.fence != fence
            or row.state != "running"
            or row.lease_expires_at is None
            or aware(row.lease_expires_at) <= m.now()
        ):
            raise ManagementError("llm_test_fenced", 409)
        config = TestConfiguration.model_validate(row.configuration)
        ledger = TestLedger.model_validate(row.ledger)
        if pins:
            current = m.permits.get(config.fingerprint)
            if current is None or LiveProbePermit.model_validate(current) != config.permit:
                raise ManagementError("llm_test_authorization_revoked", 409)
            connection = await m.connection(session, row.connection_id, locked=True)
            profile = await m.profile(session, row.profile_id, locked=True)
            if (
                not connection.enabled
                or connection.active_credential_id is None
                or connection.revision != config.connection_revision
                or profile.revision != config.profile_revision
                or profile.active_version_id != row.profile_version_id
                or connection.endpoint_policy != config.endpoint.model_dump(mode="json")
                or ledger.deadline <= m.now()
            ):
                raise ManagementError("llm_test_configuration_stale", 409)
        return row, config, ledger

    async def check(self, fence):
        async with self.management.sessions.begin() as session:
            return (await self.row(session, fence=fence))[2]

    async def claim(self):
        m = self.management
        async with m.sessions.begin() as session:
            row, config, ledger = await self.row(session, pins=False)
            if row.state in {"succeeded", "failed", "unavailable"}:
                return None
            if (
                row.state == "running"
                and row.lease_expires_at
                and aware(row.lease_expires_at) > m.now()
            ):
                return None
            if ledger.calls:
                await self.terminal(session, row, "failed", "llm_test_ambiguous_attempt")
                return None
            try:
                await self.row(session)
            except ManagementError:
                await self.terminal(session, row, "unavailable", "llm_test_configuration_stale")
                return None
            row.state, row.fence = "running", row.fence + 1
            row.lease_expires_at = m.now() + timedelta(seconds=90)
            job = await session.get(Job, row.id)
            job.status = "IN_PROGRESS"
            return row.fence, config, ledger

    async def budget(self, fence, operation, *, tokens=0, record=None):
        m = self.management
        async with m.sessions.begin() as session:
            row, config, ledger = await self.row(session, fence=fence)
            data = ledger.model_dump()
            if operation == "reserve":
                if (
                    ledger.violated
                    or ledger.calls >= min(config.permit.max_calls, config.profile.max_calls)
                    or ledger.reserved_tokens + tokens
                    > min(config.permit.max_tokens, config.profile.max_total_tokens)
                ):
                    raise ManagementError("llm_test_budget_exhausted", 409)
                data.update(calls=ledger.calls + 1, reserved_tokens=ledger.reserved_tokens + tokens)
            elif operation == "record":
                receipt = record.receipt
                if (
                    record.sequence > ledger.calls
                    or any(r.sequence == record.sequence for r in ledger.records)
                    or receipt
                    and (
                        receipt.tenant_id != m.access.tenant_id
                        or receipt.connection_id != row.connection_id
                        or receipt.actor_id != row.requested_by
                        or receipt.endpoint_approval_id != config.endpoint.approval_id
                    )
                ):
                    raise ManagementError("llm_test_receipt_invalid", 409)
                data["records"] = (*ledger.records, record)
            elif operation == "overrun":
                data["violated"] = True
            else:
                raise ManagementError("llm_test_operation_invalid", 409)
            updated = TestLedger.model_validate(data)
            row.ledger = updated.model_dump(mode="json")
            return updated

    async def execute(self, provider_factory, *, worker_identity=None, reviewed_limits=None):
        claimed = await self.claim()
        if claimed is None:
            return
        fence, config, ledger = claimed
        try:
            budget = ProbeBudget(self, fence, config, ledger)
            provider = provider_factory(config, budget, self, fence)
            if provider.budget is not budget or provider.profile != config.profile:
                raise ManagementError("llm_worker_configuration_invalid")
            async with asyncio.timeout(
                max(0.001, (ledger.deadline - self.management.now()).total_seconds())
            ):
                prober = CapabilityProber(provider, permit=config.permit)
                report = await (
                    prober.run(config.plan) if config.operation == "probe" else prober.list_models()
                )
            async with self.management.sessions.begin() as session:
                row, _, _ = await self.row(session, fence=fence)
                result = {
                    "origin": provider.transport.execution_origin,
                    "operation": config.operation,
                    "report": report.model_dump(mode="json"),
                }
                row.result = result
                successful = (
                    all(
                        o.outcome in {"completed", "tool_actions", "truncated"}
                        for o in report.observations
                    )
                    if config.operation == "probe"
                    else report.status == "completed"
                )
                if successful and config.operation == "probe":
                    await self._qualify(
                        session, row, config, report, worker_identity, reviewed_limits or {}
                    )
                row.state = "succeeded" if successful else "failed"
                job = await session.get(Job, row.id)
                job.status = "COMPLETED" if successful else "FAILED"
                job.result_payload = {"test_id": str(row.id), "state": row.state}
                self.management.audit(session, "test_finished", row.id)
        except (Exception, asyncio.CancelledError):
            async with self.management.sessions.begin() as session:
                try:
                    row, _, _ = await self.row(session, fence=fence, pins=False)
                except ManagementError:
                    return
                row.state, row.error_code = "unavailable", "llm_test_execution_unavailable"
                job = await session.get(Job, row.id)
                job.status, job.error_code = "FAILED", row.error_code

    async def _qualify(self, session, row, config, report, worker, reviews):
        # Network success alone is insufficient: operator-reviewed, exact-profile
        # limits/evidence plus trusted worker composition are mandatory.
        review = reviews.get(config.fingerprint)
        if (
            not worker
            or not review
            or row.result["origin"] != "live_network"
            or any(o.origin != "live_network" for o in report.observations)
            or not report.is_current(
                config.profile,
                self.management.endpoints.pin(config.endpoint),
                config.settings.options,
                config.plan,
            )
        ):
            return
        from uuid import UUID

        try:
            evidence_id = UUID(review["evidence_id"])
            if (
                evidence_id.int == 0
                or review["worker_identity"] != worker
                or config.settings.context_tokens > review["context_tokens"]
                or config.settings.output_tokens > review["output_tokens"]
            ):
                return
        except (KeyError, TypeError, ValueError):
            return
        observations = {o.case: o for o in report.observations}
        required = {"authentication", "model_access", "structured_output", "usage", "token_limit"}
        if config.settings.temperature is not None:
            required.add("temperature")
        if config.settings.tool_mode == "native":
            required.add("native_tools")
        if any(
            case not in observations or observations[case].support != Support.SUPPORTED
            for case in required
        ):
            return
        m = self.management
        profile = await m.profile(session, row.profile_id, locked=True)
        old = await m.version(session, profile)
        caps = ProviderCapabilities(
            qualification="live_worker",
            qualification_id=row.id,
            tested_at=m.now(),
            context_tokens=config.settings.context_tokens,
            output_tokens=config.settings.output_tokens,
            json_schema=observations["structured_output"].support,
            usage=observations["usage"].support,
            native_tools=observations["native_tools"].support
            if "native_tools" in observations
            else Support.UNKNOWN,
            temperature=observations["temperature"].support
            if "temperature" in observations
            else Support.UNKNOWN,
        )
        snapshot = ModelProfileSnapshot.model_validate(
            {
                **old.snapshot,
                "profile_version": old.version + 1,
                "capabilities": caps.model_dump(mode="json"),
            }
        )
        version = LlmModelProfileVersion(
            id=uuid4(),
            tenant_id=row.tenant_id,
            connection_id=row.connection_id,
            profile_id=row.profile_id,
            version=old.version + 1,
            snapshot=snapshot.model_dump(mode="json"),
            settings=old.settings,
            qualification_test_id=row.id,
        )
        session.add(version)
        await session.flush()
        profile.active_version_id, profile.revision = version.id, profile.revision + 1
        row.result = {
            **row.result,
            "origin": "live_worker",
            "worker_identity": worker,
            "review_evidence_id": str(evidence_id),
            "qualified_version_id": str(version.id),
        }


class ProbeBudget(CallBudget):
    def __init__(self, store, fence, config, ledger):
        super().__init__(
            max_calls=min(config.permit.max_calls, config.profile.max_calls),
            max_tokens=min(config.permit.max_tokens, config.profile.max_total_tokens),
            total_seconds=max(0.001, (ledger.deadline - store.management.now()).total_seconds()),
        )
        self.store, self.fence, self.config = store, fence, config
        self.calls, self.reserved_tokens, self._records = (
            ledger.calls,
            ledger.reserved_tokens,
            list(ledger.records),
        )

    def reserve(self, *args):
        raise ManagementError("llm_test_async_admission_required")

    def record(self, *args):
        raise ManagementError("llm_test_async_receipt_required")

    def begin_repair(self, *args):
        raise ManagementError("llm_probe_repair_unsupported")

    def observe_overrun(self, *args):
        raise ManagementError("llm_test_async_accounting_required")

    def validate_provider(self, profile, pinned, options):
        if (
            profile != self.config.profile
            or options != self.config.settings.options
            or pinned != self.store.management.endpoints.pin(self.config.endpoint)
        ):
            raise ManagementError("llm_test_configuration_stale")

    async def before_attempt(self, input_ceiling, output_ceiling):
        row = await self.store.budget(self.fence, "reserve", tokens=input_ceiling + output_ceiling)
        self.calls, self.reserved_tokens = row.calls, row.reserved_tokens
        return row.calls

    async def before_repair(self, request_id):
        raise ManagementError("llm_probe_repair_unsupported")

    async def after_attempt(self, item):
        await self.store.budget(self.fence, "record", record=item)
        self._records.append(item)

    async def after_overrun(self, extra_tokens):
        await self.store.budget(self.fence, "overrun")
