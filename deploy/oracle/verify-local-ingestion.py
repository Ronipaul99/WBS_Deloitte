"""Create one synthetic PDF through the local API and verify its active Neon vectors.

Run from backend: .venv/Scripts/python.exe ../deploy/oracle/verify-local-ingestion.py
Requires the SSH tunnel and a local API listening on port 8001. Keeps the created
smoke-test project/document so the result can be inspected in the UI.
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import UUID

import httpx
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.core.config import get_settings
from app.db.session import SessionLocal, engine, set_local_tenant_context


def synthetic_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
    })
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 16 Tf 50 740 Td (LOCAL INGESTION VERIFICATION) Tj "
        b"0 -30 Td (Project scope includes requirements and delivery milestones.) Tj "
        b"0 -30 Td (Acceptance criteria include malware scanning and stored vectors.) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


async def verify_vectors(tenant_id: UUID, document_id: str, run_id: str) -> dict:
    try:
        async with SessionLocal() as session, session.begin():
            await set_local_tenant_context(session, tenant_id)
            row = (await session.execute(text(
                "SELECT count(*) AS chunks, min(vector_dims(c.embedding)) AS dimensions, "
                "bool_and(c.processing_run_id = d.current_processing_run_id) AS active "
                "FROM document_chunks c JOIN documents d ON d.id = c.document_id "
                "WHERE c.tenant_id = :tenant AND c.document_id = :document "
                "AND c.processing_run_id = :run"
            ), {"tenant": tenant_id, "document": UUID(document_id), "run": UUID(run_id)})).one()
            assert row.chunks > 0 and row.dimensions == 384 and row.active
            return {"stored_chunks": row.chunks, "vector_dimensions": row.dimensions,
                    "active_processing_run": bool(row.active)}
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-id", type=UUID, help="Retry an existing verification document")
    args = parser.parse_args()
    settings = get_settings()
    assert settings.document_ingestion_local_development and settings.document_ingestion_enabled
    assert settings.auth_mode == "development" and not settings.tasks_eager
    tenant_id = settings.dev_tenant_id
    prefix = f"/api/v1/tenants/{tenant_id}"
    with httpx.Client(base_url="http://127.0.0.1:8001", timeout=90) as client:
        if args.document_id:
            response = client.get(f"{prefix}/documents/{args.document_id}")
            response.raise_for_status()
            project_id = response.json()["project_id"]
        else:
            response = client.post(f"{prefix}/projects", json={
                "name": f"Text PDF ingestion verification {datetime.now(UTC):%Y-%m-%d %H:%M}",
                "description": "Synthetic PDF verifying local API, VM worker and Neon vectors.",
            })
            response.raise_for_status()
            project_id = response.json()["id"]
            response = client.post(f"{prefix}/projects/{project_id}/documents", files={
                "file": ("local-ingestion-verification.pdf", synthetic_pdf(), "application/pdf")
            })
        response.raise_for_status()
        document_id = response.json()["id"]
        endpoint = f"{prefix}/documents/{document_id}/ingestions"
        response = client.post(endpoint)
        response.raise_for_status()
        job_id = response.json()["id"]
        print(json.dumps({"upload": "passed", "dispatch": "accepted", "project_id": project_id,
                          "document_id": document_id, "job_id": job_id}), flush=True)
        last_stage = None
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            response = client.get(f"{endpoint}/current")
            response.raise_for_status()
            status = response.json()
            stage = (status["status"], status["stage"], status["attempt_count"])
            if stage != last_stage:
                print(json.dumps({"status": stage[0], "stage": stage[1], "attempts": stage[2],
                                  "error_code": status["error_code"]}), flush=True)
                last_stage = stage
            if status["status"] == "COMPLETED":
                break
            if status["status"] in {"FAILED", "CANCELLED"}:
                raise RuntimeError(status["error_code"] or "ingestion failed")
            time.sleep(3)
        else:
            raise TimeoutError("ingestion did not finish within five minutes")
        vectors = asyncio.run(verify_vectors(tenant_id, document_id, status["processing_run_id"]))
        result = {"project_id": project_id, "document_id": document_id, "job_id": job_id,
                  "processing_run_id": status["processing_run_id"], **vectors}
        # Repeating the request must resolve to the same completed run/job.
        repeated = client.post(endpoint)
        repeated.raise_for_status()
        assert repeated.json()["id"] == job_id
        result["completed_request_idempotent"] = True
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"verification_error_type": type(error).__name__}), flush=True)
        raise SystemExit(1) from None
