from fastapi.testclient import TestClient

from paintmixer.api.app import create_app


def test_health() -> None:
    client = TestClient(create_app())
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
