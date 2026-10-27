"""Deterministic paged inventory. No document text is stored in inventory artifacts."""

from dataclasses import dataclass

from app.services.agents.evidence_types import (
    EvidenceError,
    InventoryManifest,
    InventoryPage,
    digest,
)


@dataclass(frozen=True)
class Inventory:
    manifest: InventoryManifest
    pages: tuple[InventoryPage, ...]

    def __post_init__(self):
        pin = self.manifest.pin
        previous, count, seen = None, 0, set()
        if len(self.pages) != self.manifest.page_count:
            raise EvidenceError("evidence_inventory_pages_missing")
        for i, page in enumerate(self.pages):
            if (
                page.index != i
                or page.pin_sha256 != digest(pin)
                or page.previous_sha256 != previous
            ):
                raise EvidenceError("evidence_inventory_chain_invalid")
            if len(page.model_dump_json().encode()) > 250000:
                raise EvidenceError("evidence_inventory_page_oversized")
            for entry in page.entries:
                if entry.ordinal != count or entry.chunk_id in seen:
                    raise EvidenceError("evidence_inventory_partition_invalid")
                count += 1
                seen.add(entry.chunk_id)
            previous = digest(page)
        if (
            count != pin.chunk_count
            or count != self.manifest.chunk_count
            or self.manifest.root_sha256 != (previous or digest([]))
        ):
            raise EvidenceError("evidence_inventory_root_invalid")

    @property
    def sha256(self):
        return digest(self.manifest)

    @property
    def entries(self):
        return tuple(e for page in self.pages for e in page.entries)

    def entry(self, identity):
        for entry in self.entries:
            if entry.chunk_id == identity:
                return entry
        raise EvidenceError("evidence_chunk_outside_inventory")

    def headings(self, identity):
        for entry in self.entries:
            if entry.section_id == identity:
                return entry.heading_path
        raise EvidenceError("evidence_section_outside_inventory")

    def verify(self, chunk):
        if self.entry(chunk.descriptor.chunk_id) != chunk.descriptor:
            raise EvidenceError("evidence_canonical_input_changed")


async def build_inventory(repository, expected_pin=None):
    pin = expected_pin or await repository.pin()
    pages, pending, after, previous = [], [], -1, None

    def flush():
        nonlocal pending, previous
        page = InventoryPage(
            pin_sha256=digest(pin),
            index=len(pages),
            previous_sha256=previous,
            entries=tuple(pending),
        )
        pages.append(page)
        previous, pending = digest(page), []

    while True:
        result = await repository.page(pin, after=after, limit=32)
        if result.pin_sha256 != digest(pin) or result.after_ordinal != after:
            raise EvidenceError("evidence_inventory_cursor_invalid")
        for chunk in result.chunks:
            if len(pending) == 64:
                flush()
            candidate = InventoryPage(
                pin_sha256=digest(pin),
                index=len(pages),
                previous_sha256=previous,
                entries=tuple(pending + [chunk.descriptor]),
            )
            if len(candidate.model_dump_json().encode()) > 250000 or len(pending) == 64:
                if not pending:
                    raise EvidenceError("evidence_inventory_entry_oversized")
                flush()
            pending.append(chunk.descriptor)
            if (
                len(
                    InventoryPage(
                        pin_sha256=digest(pin),
                        index=len(pages),
                        previous_sha256=previous,
                        entries=tuple(pending),
                    )
                    .model_dump_json()
                    .encode()
                )
                > 250000
            ):
                raise EvidenceError("evidence_inventory_entry_oversized")
        if result.next_ordinal is None:
            break
        if not result.chunks or result.next_ordinal <= after:
            raise EvidenceError("evidence_inventory_cursor_invalid")
        after = result.next_ordinal
    if pending:
        flush()
    await repository.guard(pin)
    return Inventory(
        InventoryManifest(
            pin=pin,
            root_sha256=previous or digest([]),
            page_count=len(pages),
            chunk_count=pin.chunk_count,
        ),
        tuple(pages),
    )
