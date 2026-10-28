"""Frozen pre-Step-4 shape for isolated historical migration checks only."""

from sqlalchemy import MetaData

from app.db.base import Base


def pre_import_metadata(exclude=()):
    metadata = MetaData()
    for table in Base.metadata.tables.values():
        if table.name not in {*exclude, "summary_result_imports"}:
            table.to_metadata(metadata)
    summary = metadata.tables["document_summaries"]
    constraint = next(c for c in summary.constraints if c.name == "fk_summary_external_source")
    for fk in constraint.elements:
        summary.foreign_keys.discard(fk)
        fk.parent.foreign_keys.discard(fk)
    summary.constraints.remove(constraint)
    for name in ("source_request_id", "structured_summary"):
        summary._columns.remove(summary.c[name])
    if "summary_api_requests" in metadata.tables:
        request = metadata.tables["summary_api_requests"]
        request.constraints.remove(
            next(c for c in request.constraints if c.name == "uq_summary_request_document")
        )
    return metadata
