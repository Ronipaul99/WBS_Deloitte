"""Authorized application checkpoints, not a general BaseCheckpointSaver.

Only immutable completed-node reads/listing are supported. Framework config edits,
pending writes, deletion, copying, pruning, delta histories and nested namespaces
are intentionally unavailable. Writes use WorkflowStore.complete's fenced txn.
"""

from uuid import UUID

from sqlalchemy import select

from app.models.agent_workflows import AgentCheckpoint
from app.services.agents.repository import WorkflowRepository
from app.services.agents.state import OrchestrationArtifact, node_input_hash


class ScopedCheckpoints:
    def __init__(self, store):
        self._store = store

    async def list(self, *, before: int | None = None, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("checkpoint page limit invalid")
        if before is not None and (type(before) is not int or before < 1):
            raise ValueError("checkpoint cursor invalid")
        store = self._store
        async with store.sessions.begin() as session:
            repo = WorkflowRepository(session, store.access, store.scope)
            await repo._authorize()
            run = await repo._run()
            if run.requested_by != store.access.user_id:
                raise PermissionError("checkpoint access denied")
            await repo._current_source()
            query = select(AgentCheckpoint).where(
                AgentCheckpoint.tenant_id == store.access.tenant_id,
                AgentCheckpoint.workflow_run_id == store.scope.workflow_run_id,
            )
            if before is not None:
                query = query.where(AgentCheckpoint.sequence < before)
            rows = (
                await session.scalars(query.order_by(AgentCheckpoint.sequence.desc()).limit(limit))
            ).all()
            artifacts = []
            for row in rows:
                artifact = OrchestrationArtifact.model_validate(row.artifact)
                if (
                    artifact.payload.workflow_run_id != run.id
                    or artifact.payload.input_sha256
                    != node_input_hash(run.input_snapshot, artifact.payload.before)
                    or row.sequence != artifact.payload.after.sequence
                    or row.input_sha256 != artifact.payload.input_sha256
                ):
                    raise ValueError("incompatible checkpoint")
                artifacts.append(artifact.payload)
            return tuple(artifacts)

    async def get(self, checkpoint_id: UUID):
        store = self._store
        async with store.sessions.begin() as session:
            repo = WorkflowRepository(session, store.access, store.scope)
            row = await repo.checkpoint(checkpoint_id)
            if row is None:
                raise PermissionError("checkpoint unavailable")
            sequence = row.sequence
        page = await self.list(before=sequence + 1, limit=1)
        if not page or page[0].after.sequence != sequence:
            raise PermissionError("checkpoint unavailable")
        return page[0]

    def unsupported(self, *args, **kwargs):
        raise NotImplementedError("application checkpoint operation unavailable")

    # No accidental delegation to an unguarded framework saver/connection.
    put = put_writes = delete_thread = copy_thread = prune = unsupported
    get_tuple = get_delta_channel_history = list_threads = unsupported
    aput = aput_writes = adelete_thread = acopy_thread = aprune = unsupported
    aget_tuple = aget_delta_channel_history = adelete_for_runs = unsupported
