"""Canonical citation and lifecycle boundaries; no generation agents or routes."""

import asyncio
import math
from uuid import NAMESPACE_URL, uuid5

from app.services.agents.contracts import EvidenceReference, WorkflowInput
from app.services.agents.evidence_types import EvidenceError, digest
from app.services.agents.repository import WorkflowRepository
from app.services.ingestion.pinned import PinnedEvidenceRepository
from app.services.ingestion.query_aliases import expand_alias_terms
from app.services.ingestion.retrieval import fuse_candidates, lexical_terms


async def repository_for_workflow(store):
    """Derive source from an authorized persisted run, never from tool/config fields."""
    async with store.sessions.begin() as session:
        repo = WorkflowRepository(session, store.access, store.scope)
        await repo._authorize()
        run = await repo._run()
        if run.requested_by != store.access.user_id or run.state in {
            "cancelled",
            "stale",
            "failed",
        }:
            raise EvidenceError("evidence_workflow_unavailable")
        await repo._current_source()
        workflow = WorkflowInput.model_validate(run.input_snapshot)
        if workflow.scope != store.scope.source:
            raise EvidenceError("evidence_workflow_scope_mismatch")
    return PinnedEvidenceRepository(store.sessions, store.access, workflow.scope)


class EvidenceAccess:
    def __init__(self, repository, inventory):
        if repository.source != inventory.manifest.pin.scope:
            raise EvidenceError("evidence_inventory_scope_mismatch")
        self.repository, self.inventory = repository, inventory
        self.pin = inventory.manifest.pin

    async def guard(self):
        """Call before new reads/calls and immediately before later publication."""
        await self.repository.guard(self.pin)

    async def publication_guard(self):
        """Later publication must recheck every descriptor, not only cited chunks."""
        after, seen = -1, 0
        entries = self.inventory.entries
        while True:
            page = await self.repository.page(self.pin, after=after)
            for chunk in page.chunks:
                if seen >= len(entries) or chunk.descriptor != entries[seen]:
                    raise EvidenceError("evidence_canonical_input_changed")
                seen += 1
            if page.next_ordinal is None:
                break
            if page.next_ordinal <= after:
                raise EvidenceError("evidence_inventory_cursor_invalid")
            after = page.next_ordinal
        if seen != len(entries):
            raise EvidenceError("evidence_inventory_incomplete")
        await self.guard()

    async def chunks(self, identities):
        for identity in identities:
            self.inventory.entry(identity)
        chunks = await self.repository.chunks(self.pin, identities)
        for chunk in chunks:
            self.inventory.verify(chunk)
        return chunks

    async def section(self, section, cursor=0):
        headings = self.inventory.headings(section)
        ordinals = [e.ordinal for e in self.inventory.entries if e.section_id == section]
        if cursor and cursor not in ordinals:
            raise EvidenceError("evidence_section_cursor_invalid")
        page = await self.repository.page(self.pin, after=cursor - 1, limit=4, headings=headings)
        for chunk in page.chunks:
            self.inventory.verify(chunk)
        next_cursor = None
        if page.next_ordinal is not None:
            next_cursor = next(n for n in ordinals if n > page.next_ordinal)
        return page.chunks, next_cursor

    async def neighbors(self, identities, radius):
        wanted = set()
        entries = self.inventory.entries
        for identity in identities:
            entry = self.inventory.entry(identity)
            wanted.update(
                e.chunk_id
                for e in entries[max(0, entry.ordinal - radius) : entry.ordinal + radius + 1]
            )
        if len(wanted) > 50:
            raise EvidenceError("evidence_neighbors_excessive")
        return await self.chunks(tuple(sorted(wanted, key=str)))

    async def definitions(self, term):
        chunks, more = await self.repository.definitions(self.pin, term)
        for chunk in chunks:
            self.inventory.verify(chunk)
        return chunks, more

    async def reference(self, identity, start, end, *, quote=None, chunk_sha256=None):
        (chunk,) = await self.chunks((identity,))
        d = chunk.descriptor
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(chunk.content)
            or end - start > 20000
            or not d.physical_pages
            or quote is not None
            and quote != chunk.content[start:end]
            or chunk_sha256 is not None
            and chunk_sha256 != d.chunk_sha256
        ):
            raise EvidenceError("evidence_locator_invalid")
        # No persisted character-to-reference map exists. Context rows/pages are
        # included conservatively; they cannot inherit the primary row's locator.
        refs = list(d.source_references)
        tables = {(r.page_number, r.table_index) for r in refs}
        rows = {r.row_index for r in refs}
        table_id = row_id = None
        if len(tables) == 1:
            page, table = next(iter(tables))
            if page is not None and table is not None:
                table_id = f"page:{page}/table:{table}"
                if len(rows) == 1 and None not in rows:
                    row_id = f"row:{next(iter(rows))}"
        try:
            return EvidenceReference(
                evidence_id=uuid5(
                    NAMESPACE_URL,
                    digest(
                        {
                            "pin": digest(self.pin),
                            "chunk": str(identity),
                            "text": d.text_sha256,
                            "start": start,
                            "end": end,
                        }
                    ),
                ),
                scope=self.pin.scope,
                chunk_id=identity,
                chunk_sha256=d.chunk_sha256,
                physical_pages=d.physical_pages,
                heading_path=d.heading_path,
                exact_quote=chunk.content[start:end],
                char_start=start,
                char_end=end,
                printed_page_label=d.printed_page_label if len(d.physical_pages) == 1 else None,
                table_id=table_id,
                row_id=row_id,
            )
        except ValueError:
            raise EvidenceError("evidence_locator_metadata_bounds") from None

    async def validate_reference(self, reference):
        if reference.scope != self.pin.scope:
            raise EvidenceError("evidence_locator_scope_mismatch")
        expected = await self.reference(
            reference.chunk_id,
            reference.char_start,
            reference.char_end,
            quote=reference.exact_quote,
            chunk_sha256=reference.chunk_sha256,
        )
        if reference != expected:
            raise EvidenceError("evidence_locator_metadata_mismatch")
        return reference


class PinnedRetriever:
    def __init__(self, evidence, provider, *, reranker=None):
        self.evidence, self.provider, self.reranker = evidence, provider, reranker

    async def search(self, query, *, section=None, limit=5):
        if type(limit) is not int or not 1 <= limit <= 20:
            raise EvidenceError("evidence_search_limit_invalid")
        evidence, p = self.evidence, self.provider
        identity = evidence.pin.processing
        actual = (
            p.provider_name,
            p.model_name,
            p.model_revision,
            p.dimensions,
            p.formatting_version,
        )
        if actual != (
            identity.embedding_provider,
            identity.embedding_model,
            identity.embedding_model_revision,
            384,
            identity.embedding_formatting_version,
        ):
            raise EvidenceError("evidence_query_embedding_identity_mismatch")
        headings = evidence.inventory.headings(section) if section is not None else None
        terms = lexical_terms(query)
        await evidence.guard()
        if not terms:
            return ()
        paths = [e.heading_path for e in evidence.inventory.entries]
        terms = expand_alias_terms(terms, paths)
        vector = await asyncio.to_thread(p.embed_query, query)
        semantic, lexical = await evidence.repository.candidates(
            evidence.pin, vector, terms, headings=headings
        )
        hits = fuse_candidates(semantic, lexical, limit=60)
        if self.reranker and hits:
            scores = await asyncio.to_thread(
                self.reranker.score,
                query,
                [" > ".join(h.heading_path) + "\n" + h.content for h in hits],
            )
            if len(scores) != len(hits) or any(not math.isfinite(s) for s in scores):
                raise EvidenceError("evidence_reranker_invalid")
            hits = tuple(
                h
                for _, h in sorted(
                    zip(scores, hits, strict=True), key=lambda pair: (-pair[0], pair[1].ordinal)
                )
            )
        selected = hits[:limit]
        if selected:
            chunks = await evidence.chunks(tuple(h.chunk_id for h in selected))
            canonical = {c.descriptor.chunk_id: c for c in chunks}
            if any(
                h.processing_run_id != evidence.pin.scope.processing_run_id
                or h.content != canonical[h.chunk_id].content
                for h in selected
            ):
                raise EvidenceError("evidence_search_input_changed")
        await evidence.guard()
        return selected
