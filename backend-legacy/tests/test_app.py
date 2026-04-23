from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_documents_endpoint():
    response = client.get("/documents")
    assert response.status_code == 200
    assert "count" in response.json()
    assert "documents" in response.json()