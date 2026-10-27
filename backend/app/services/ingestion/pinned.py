"""Read-only agent evidence repository. Explicit pinned predicates on every query.

No settings/engine/model downloads; sessions and authenticated access are injected.
"""

import hashlib
import math
from contextlib import asynccontextmanager

from sqlalchemy import Text, and_, func, literal, select
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.exc import SQLAlchemyError

from app.core.permissions import Permission
from app.models.domain import Document, DocumentChunk, DocumentProcessingRun, Project
from app.services.agents.evidence_types import (
    CanonicalEvidenceChunk,
    ChunkDescriptor,
    ChunkPage,
    EvidenceError,
    EvidencePin,
    ProcessingVersion,
    SourceRef,
    digest,
)
from app.services.agents.scoped_storage import ScopedStorage
from app.services.ingestion.embeddings.base import EmbeddingVector


def section_id(pin, headings):
    return digest({"pin": digest(pin), "headings": list(headings)})


class PinnedEvidenceRepository:
    def __init__(self, sessions, access, source):
        if access.tenant_id != source.tenant_id:
            raise PermissionError("evidence scope denied")
        self.sessions, self.access, self.source = sessions, access, source

    def predicates(self):
        s = self.source
        return (
            DocumentChunk.tenant_id == s.tenant_id,
            DocumentChunk.project_id == s.project_id,
            DocumentChunk.document_id == s.document_id,
            DocumentChunk.processing_run_id == s.processing_run_id,
        )

    @asynccontextmanager
    async def transaction(self, expected=None):
        try:
            async with self.sessions.begin() as session:
                scoped = ScopedStorage(session, self.access)
                await scoped.authorize(Permission.DOCUMENT_READ)
                await scoped.authorize(Permission.LLM_USE)
                pin = await self._pin(session)
                if expected is not None and expected != pin:
                    raise EvidenceError("evidence_input_stale")
                yield session, pin
                # Detect committed lifecycle/activation changes during this short read.
                if pin != await self._pin(session):
                    raise EvidenceError("evidence_input_stale")
        except SQLAlchemyError:
            raise EvidenceError("evidence_storage_unavailable") from None

    async def _pin(self, session):
        s = self.source
        pair = (
            await session.execute(
                select(Document, DocumentProcessingRun)
                .join(
                    DocumentProcessingRun,
                    and_(
                        DocumentProcessingRun.id == s.processing_run_id,
                        DocumentProcessingRun.document_id == Document.id,
                        DocumentProcessingRun.tenant_id == Document.tenant_id,
                        DocumentProcessingRun.project_id == Document.project_id,
                    ),
                )
                .join(
                    Project,
                    and_(
                        Project.id == Document.project_id, Project.tenant_id == Document.tenant_id
                    ),
                )
                .where(
                    Document.id == s.document_id,
                    Document.tenant_id == s.tenant_id,
                    Document.project_id == s.project_id,
                )
                .execution_options(populate_existing=True)
            )
        ).first()
        if pair is None:
            raise EvidenceError("evidence_scope_unavailable")
        doc, run = pair
        if (
            doc.lifecycle_status != "ACTIVE"
            or doc.vectors_hidden_at is not None
            or doc.current_processing_run_id != s.processing_run_id
            or run.status != "COMPLETED"
            or doc.processing_status != "COMPLETED"
            or run.document_content_sha256 != s.source_sha256
            or doc.content_sha256 != s.source_sha256
        ):
            raise EvidenceError("evidence_source_stale_or_unreadable")
        try:
            processing = ProcessingVersion.model_validate(
                {
                    k: getattr(run, k)
                    for k in ProcessingVersion.model_fields
                    if k != "schema_version"
                }
            )
            pin = EvidencePin(
                scope=s,
                processing=processing,
                chunk_count=run.chunk_count,
                page_count=run.page_count,
                warning_codes=tuple(run.warning_codes),
            )
        except (ValueError, TypeError):
            raise EvidenceError("evidence_processing_identity_unavailable") from None
        count, low, high = (
            await session.execute(
                select(
                    func.count(), func.min(DocumentChunk.ordinal), func.max(DocumentChunk.ordinal)
                ).where(*self.predicates())
            )
        ).one()
        if count != pin.chunk_count or count and (low != 0 or high != count - 1):
            raise EvidenceError("evidence_inventory_incomplete")
        return pin

    async def pin(self):
        async with self.transaction() as (_, pin):
            return pin

    async def guard(self, pin):
        async with self.transaction(pin):
            pass

    @staticmethod
    def canonical(pin, row):
        meta = row.source_metadata
        try:
            if row.block_type != "canonical_chunk" or len(str(meta).encode()) > 131072:
                raise ValueError()
            refs = tuple(SourceRef.model_validate(r) for r in meta.get("source_references", ()))
            # Do not infer page numbers from heading text or printed page labels.
            pages = tuple(sorted({r.page_number for r in refs if r.page_number is not None}))
            if any(p > pin.page_count for p in pages):
                raise ValueError()
            if tuple(meta.get("page_numbers", ())) != pages:
                raise ValueError()
            if row.page_number is not None and pages != (row.page_number,):
                raise ValueError()
            if tuple(meta.get("primary_source_block_ordinals", ())) != tuple(
                dict.fromkeys(r.block_ordinal for r in refs if r.role == "primary")
            ):
                raise ValueError()
            headings = tuple(row.heading_path)
            descriptor = ChunkDescriptor(
                chunk_id=row.id,
                ordinal=row.ordinal,
                chunk_sha256=row.content_sha256,
                text_sha256=hashlib.sha256(row.content.encode()).hexdigest(),
                metadata_sha256=digest(meta),
                characters=len(row.content),
                section_id=section_id(pin, headings),
                heading_path=headings,
                physical_pages=pages,
                source_references=refs,
                warning_codes=tuple(meta.get("warning_codes", ())),
                printed_page_label=meta.get("printed_page_label"),
            )
            return CanonicalEvidenceChunk(descriptor=descriptor, content=row.content)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise EvidenceError("evidence_canonical_metadata_invalid") from None

    async def page(self, pin, *, after=-1, limit=32, headings=None):
        if (
            type(after) is not int
            or not -1 <= after < max(1, pin.chunk_count)
            or type(limit) is not int
            or not 1 <= limit <= 64
        ):
            raise EvidenceError("evidence_cursor_invalid")
        async with self.transaction(pin) as (session, _):
            query = select(DocumentChunk).where(*self.predicates(), DocumentChunk.ordinal > after)
            if headings is not None:
                query = query.where(DocumentChunk.heading_path == list(headings))
            rows = (
                await session.scalars(query.order_by(DocumentChunk.ordinal).limit(limit + 1))
            ).all()
            chunks = tuple(self.canonical(pin, r) for r in rows[:limit])
            return ChunkPage(
                pin_sha256=digest(pin),
                after_ordinal=after,
                chunks=chunks,
                next_ordinal=chunks[-1].descriptor.ordinal if len(rows) > limit else None,
            )

    async def chunks(self, pin, identities):
        identities = tuple(identities)
        if not identities or len(identities) > 64 or len(set(identities)) != len(identities):
            raise EvidenceError("evidence_chunk_ids_invalid")
        async with self.transaction(pin) as (session, _):
            rows = (
                await session.scalars(
                    select(DocumentChunk)
                    .where(*self.predicates(), DocumentChunk.id.in_(identities))
                    .order_by(DocumentChunk.ordinal)
                )
            ).all()
            if {r.id for r in rows} != set(identities):
                raise EvidenceError("evidence_chunk_outside_scope")
            return tuple(self.canonical(pin, r) for r in rows)

    async def definitions(self, pin, term):
        async with self.transaction(pin) as (session, _):
            rows = (
                await session.scalars(
                    select(DocumentChunk)
                    .where(
                        *self.predicates(),
                        DocumentChunk.heading_path.cast(Text).ilike("%GLOSSARY%"),
                        (
                            DocumentChunk.content.icontains(term, autoescape=True)
                            | DocumentChunk.heading_path.cast(Text).icontains(term, autoescape=True)
                        ),
                    )
                    .order_by(DocumentChunk.ordinal)
                    .limit(5)
                )
            ).all()
            return tuple(self.canonical(pin, r) for r in rows[:4]), len(rows) > 4

    async def candidates(self, pin, vector, terms, *, headings=None, limit=30):
        if (
            not isinstance(vector, EmbeddingVector)
            or vector.dimensions != 384
            or not any(vector.values)
            or type(limit) is not int
            or not 1 <= limit <= 30
            or len(terms) > 64
            or any(not t.isalnum() or len(t) > 2000 for t in terms)
        ):
            raise EvidenceError("evidence_search_invalid")
        async with self.transaction(pin) as (session, _):
            if session.get_bind().dialect.name != "postgresql":
                raise EvidenceError("evidence_pgvector_required")
            distance = DocumentChunk.embedding.cosine_distance(list(vector.values)).label(
                "distance"
            )
            statement = select(DocumentChunk, distance).where(*self.predicates())
            if headings is not None:
                statement = statement.where(DocumentChunk.heading_path == list(headings))
            semantic = (
                await session.execute(
                    statement.order_by(distance, DocumentChunk.ordinal).limit(limit)
                )
            ).all()
            config = literal("simple").cast(REGCONFIG)
            search = func.to_tsvector(
                config, DocumentChunk.content + literal(" ") + DocumentChunk.heading_path.cast(Text)
            )
            tsquery = func.to_tsquery(config, " | ".join(terms))
            lexical = (
                []
                if not terms
                else (
                    await session.execute(
                        statement.where(search.op("@@")(tsquery))
                        .order_by(func.ts_rank_cd(search, tsquery).desc(), DocumentChunk.ordinal)
                        .limit(limit)
                    )
                ).all()
            )

            def records(rows):
                if any(d is None or not math.isfinite(float(d)) for _, d in rows):
                    raise EvidenceError("evidence_vector_distance_invalid")
                return tuple(
                    {
                        "id": r.id,
                        "processing_run_id": pin.scope.processing_run_id,
                        "ordinal": r.ordinal,
                        "content": self.canonical(pin, r).content,
                        "heading_path": r.heading_path,
                        "source_metadata": r.source_metadata,
                        "distance": float(d),
                    }
                    for r, d in rows
                )

            return records(semantic), records(lexical)
