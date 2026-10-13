def test_health_endpoints(client):
    live = client.get("/api/v1/health/live")
    ready = client.get("/api/v1/health/ready")

    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


def test_development_identity(client, tenant_id):
    response = client.get("/api/v1/me")

    assert response.status_code == 200
    assert response.json()["email"] == "developer@example.com"
    assert response.json()["tenants"][0]["id"] == tenant_id
