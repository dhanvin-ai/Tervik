"""Phase 3 gate: setup status, streaming ingestion, skill re-run safety."""
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path / 'phase3.db'}")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def signup(client, email="owner@example.com"):
    response = client.post("/api/auth/signup", json={"email": email, "password": "password-123"})
    assert response.status_code == 201, response.text
    return response.json()


def test_setup_status_guides_connection(client):
    owner = signup(client)
    headers = {"Authorization": f'Bearer {owner["session"]}'}
    project = client.post(f'/api/orgs/{owner["organization"]["id"]}/projects',
                          json={"name": "Shop"}, headers=headers).json()
    pid = project["id"]
    before = client.get(f"/api/projects/{pid}/setup", headers=headers).json()
    assert before["key_configured"] is True
    assert before["events_received"] == 0
    assert before["last_event_at"] is None
    assert before["jobs"] == {"pending": 0, "processed": 0, "failed": 0, "dead": 0, "expired": 0}
    ingest = {"Authorization": f'Bearer {project["credential"]["secret"]}'}
    assert client.post("/v1/events", json={"events": [
        {"id": "e-1", "conversation_id": "c-1", "role": "user", "content": "Hello"}]},
        headers=ingest).status_code == 200
    after = client.get(f"/api/projects/{pid}/setup", headers=headers).json()
    assert after["events_received"] == 1
    assert after["conversations"] == 1
    assert after["last_event_at"] is not None
    # Ingest keys cannot read setup status; other orgs see nothing.
    assert client.get(f"/api/projects/{pid}/setup", headers=ingest).status_code == 401
    outsider = signup(client, "other@example.com")
    other = {"Authorization": f'Bearer {outsider["session"]}'}
    assert client.get(f"/api/projects/{pid}/setup", headers=other).status_code == 404


def test_setup_status_for_legacy_project(client):
    project = client.post("/api/projects", json={"name": "Legacy"}).json()
    status = client.get(f'/api/projects/{project["id"]}/setup').json()
    assert status["key_configured"] is True
    assert status["events_received"] == 0
