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
        files={"file": ("scope.pdf", b"placeholder scope", "application/pdf")},
    )
    assert document_response.status_code == 201
    document_id = document_response.json()["id"]

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
                b"placeholder template",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert template_response.status_code == 201
    template_id = template_response.json()["id"]

    generation_response = client.post(
        f"/api/v1/tenants/{tenant_id}/projects/{project_id}/generations",
        json={
            "document_id": document_id,
            "template_id": template_id,
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
