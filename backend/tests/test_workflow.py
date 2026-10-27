from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.domain import (
    Document,
    DocumentChunk,
    DocumentProcessingRun,
    DocumentProcessingStatus,
    Job,
    JobType,
    ProcessingStatus,
)
from tests.pdf_fixtures import text_pdf_bytes


def _xlsx_bytes() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("xl/workbook.xml", "<workbook />")
    return output.getvalue()


async def _seed_ready_ingestion(document_id: UUID) -> None:
    async with SessionLocal() as db:
        document = await db.scalar(select(Document).where(Document.id == document_id))
        assert document is not None
        job = Job(
            tenant_id=document.tenant_id,
            project_id=document.project_id,
            created_by=document.uploaded_by,
            job_type=JobType.DOCUMENT_INGESTION.value,
            status=ProcessingStatus.COMPLETED.value,
            progress=100,
            current_step="COMPLETED",
        )
        db.add(job)
        await db.flush()
        run = DocumentProcessingRun(
            tenant_id=document.tenant_id,
            project_id=document.project_id,
            document_id=document.id,
            job_id=job.id,
            status=DocumentProcessingStatus.COMPLETED.value,
            document_content_sha256="a" * 64,
            extractor_name="pypdf-ocrmypdf",
            extractor_version="1.0.0",
            chunker_version="1.0.0",
            embedding_provider="fastembed",
            embedding_model="BAAI/bge-small-en-v1.5",
            embedding_model_revision="synthetic-model-revision",
            embedding_dimensions=384,
            embedding_formatting_version="bge-small-en-v1.5-format-v1",
            page_count=1,
            block_count=1,
            chunk_count=1,
            completed_at=datetime.now(UTC),
            current_stage="COMPLETED",
        )
        db.add(run)
        await db.flush()
        db.add(
            DocumentChunk(
                processing_run_id=run.id,
                tenant_id=document.tenant_id,
                project_id=document.project_id,
                document_id=document.id,
                ordinal=0,
                token_count=4,
                content="Synthetic project scope",
                content_sha256="b" * 64,
                block_type="canonical",
                page_number=1,
                heading_path=[],
                source_metadata={"source_references": []},
                embedding=[0.0] * 384,
            )
        )
        document.content_sha256 = run.document_content_sha256
        document.current_processing_run_id = run.id
        document.processing_status = DocumentProcessingStatus.COMPLETED.value
        document.processed_at = run.completed_at
        await db.commit()


async def _toggle_active_ingestion(document_id: UUID, enabled: bool) -> None:
    async with SessionLocal() as db:
        document = await db.scalar(select(Document).where(Document.id == document_id))
        assert document is not None
        if enabled:
            run = await db.scalar(
                select(DocumentProcessingRun)
                .where(
                    DocumentProcessingRun.document_id == document_id,
                    DocumentProcessingRun.status == DocumentProcessingStatus.COMPLETED.value,
                )
                .order_by(DocumentProcessingRun.created_at.desc())
            )
            assert run is not None
            document.current_processing_run_id = run.id
        else:
            document.current_processing_run_id = None
        await db.commit()


def test_project_summary_generation_validation_and_export(client, tenant_id):
    project_response = client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": "Solar Plant", "description": "Test project"},
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    document_response = client.post(
        f"/api/v1/tenants/{tenant_id}/projects/{project_id}/documents",
        data={"kind": "PROJECT"},
        files={"file": ("scope.pdf", text_pdf_bytes(), "application/pdf")},
    )
    assert document_response.status_code == 201
    document_id = document_response.json()["id"]

    not_ready = client.post(f"/api/v1/tenants/{tenant_id}/documents/{document_id}/summary")
    assert not_ready.status_code == 409
    assert not_ready.json()["detail"]["code"] == "DOCUMENT_INGESTION_REQUIRED"
    client.portal.call(_seed_ready_ingestion, UUID(document_id))

    summary_job_response = client.post(
        f"/api/v1/tenants/{tenant_id}/documents/{document_id}/summary"
    )
    assert summary_job_response.status_code == 202
    summary_job_id = summary_job_response.json()["id"]
    summary_job = client.get(f"/api/v1/tenants/{tenant_id}/jobs/{summary_job_id}")
    assert summary_job.json()["status"] == "COMPLETED"

    summary_response = client.get(f"/api/v1/tenants/{tenant_id}/documents/{document_id}/summary")
    assert summary_response.status_code == 200
    summary_id = summary_response.json()["id"]

    approval_response = client.post(
        f"/api/v1/tenants/{tenant_id}/documents/{document_id}/summary/approve"
    )
    assert approval_response.status_code == 200
    assert approval_response.json()["is_approved"] is True

    template_response = client.post(
        f"/api/v1/tenants/{tenant_id}/templates",
        data={"name": "Solar Template"},
        files={
            "file": (
                "template.xlsx",
                _xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert template_response.status_code == 201
    assert template_response.json()["id"]

    client.portal.call(_toggle_active_ingestion, UUID(document_id), False)
    generation_without_ready_run = client.post(
        f"/api/v1/tenants/{tenant_id}/projects/{project_id}/generations",
        json={"document_id": document_id, "summary_id": summary_id},
    )
    assert generation_without_ready_run.status_code == 409
    assert generation_without_ready_run.json()["detail"]["code"] == "DOCUMENT_INGESTION_REQUIRED"
    client.portal.call(_toggle_active_ingestion, UUID(document_id), True)

    generation_response = client.post(
        f"/api/v1/tenants/{tenant_id}/projects/{project_id}/generations",
        json={
            "document_id": document_id,
            "summary_id": summary_id,
        },
    )
    assert generation_response.status_code == 202
    generation_job_id = generation_response.json()["id"]
    generation_job = client.get(f"/api/v1/tenants/{tenant_id}/jobs/{generation_job_id}")
    assert generation_job.json()["status"] == "COMPLETED"

    wbs_response = client.get(f"/api/v1/tenants/{tenant_id}/projects/{project_id}/wbs/latest")
    assert wbs_response.status_code == 200
    wbs_version_id = wbs_response.json()["id"]
    assert wbs_response.json()["tree"][0]["name"] == "Solar Plant"

    exact_wbs_response = client.get(f"/api/v1/tenants/{tenant_id}/wbs/{wbs_version_id}")
    assert exact_wbs_response.status_code == 200
    assert exact_wbs_response.json()["id"] == wbs_version_id
    assert exact_wbs_response.json()["tree"][0]["name"] == "Solar Plant"

    validation_response = client.post(
        f"/api/v1/tenants/{tenant_id}/wbs/{wbs_version_id}/validations"
    )
    assert validation_response.status_code == 202
    validation_id = validation_response.json()["id"]
    completed_validation = client.get(f"/api/v1/tenants/{tenant_id}/validations/{validation_id}")
    assert completed_validation.json()["status"] == "COMPLETED"

    export_response = client.post(
        f"/api/v1/tenants/{tenant_id}/wbs/{wbs_version_id}/exports",
        json={"format": "json"},
    )
    assert export_response.status_code == 202
    export_id = export_response.json()["id"]
    completed_export = client.get(f"/api/v1/tenants/{tenant_id}/exports/{export_id}")
    assert completed_export.json()["status"] == "COMPLETED"
    assert completed_export.json()["download_url"]

    download = client.get(completed_export.json()["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/json")


def test_unknown_tenant_is_not_exposed(client):
    response = client.get("/api/v1/tenants/00000000-0000-0000-0000-000000000099/projects")
    assert response.status_code == 404


def test_uploads_reject_extension_and_content_type_mismatch(client, tenant_id):
    project = client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": "Upload validation"},
    )
    project_id = project.json()["id"]

    document = client.post(
        f"/api/v1/tenants/{tenant_id}/projects/{project_id}/documents",
        data={"kind": "PROJECT"},
        files={"file": ("scope.pdf", b"not a declared PDF", "text/plain")},
    )
    assert document.status_code == 415
    assert document.json()["detail"]["code"] == "DOCUMENT_TYPE_MISMATCH"

    template = client.post(
        f"/api/v1/tenants/{tenant_id}/templates",
        files={"file": ("template.xlsx", b"not a declared workbook", "application/pdf")},
    )
    assert template.status_code == 415


def test_uploads_reject_spoofed_file_content(client, tenant_id):
    project = client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": "Content validation"},
    )
    project_id = project.json()["id"]

    document = client.post(
        f"/api/v1/tenants/{tenant_id}/projects/{project_id}/documents",
        data={"kind": "PROJECT"},
        files={"file": ("scope.pdf", b"plain text", "application/pdf")},
    )
    assert document.status_code == 415
    assert document.json()["detail"] == {
        "code": "DOCUMENT_TYPE_MISMATCH",
        "message": "Uploaded content does not match the declared document type.",
    }


def test_frontend_workflow_contracts_are_exposed_in_openapi(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    generation = schemas["GenerationCreate"]
    assert set(generation["required"]) == {"document_id", "summary_id"}
    assert "template_id" in generation["properties"]
    assert "template_id" not in generation["required"]

    assert {
        "id",
        "tenant_id",
        "status",
        "progress",
        "result_payload",
    }.issubset(schemas["JobResponse"]["properties"])
    assert {
        "id",
        "project_id",
        "version_number",
        "tree",
        "scope_coverage",
    }.issubset(schemas["WbsVersionResponse"]["properties"])
    assert {"id", "status", "result"}.issubset(schemas["ValidationResponse"]["properties"])
    assert {"id", "status", "format", "download_url"}.issubset(
        schemas["ExportResponse"]["properties"]
    )
