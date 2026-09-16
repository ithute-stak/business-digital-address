from fastapi.testclient import TestClient

from app.server import app


client = TestClient(app)


def test_liveness_does_not_require_authentication() -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "business-digital-address"}


def test_readiness_checks_database_connectivity() -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ready", "service": "business-digital-address"}
