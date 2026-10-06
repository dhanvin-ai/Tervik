"""Phase 2 completion gate: accounts, durable ingestion, cross-org isolation."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path / 'phase2.db'}")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def signup(client, email="owner@example.com", password="password-123", name=None):
    body = {"email": email, "password": password}
    if name:
        body["name"] = name
    response = client.post("/api/auth/signup", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def auth(headers_session):
    return {"Authorization": f"Bearer {headers_session}"}


def event(id="e-1", conversation_id="c-1", **values):
    return {"id": id, "conversation_id": conversation_id, "role": "user",
            "content": "Hello world", **values}


def test_signup_login_logout_and_me(client):
    created = signup(client)
    assert created["session"].startswith("tvs_")
    me = client.get("/api/me", headers=auth(created["session"]))
    assert me.status_code == 200
    assert me.json()["organizations"][0]["role"] == "owner"
    assert client.get("/api/me").status_code == 401
    login = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "password-123"})
    assert login.status_code == 200
    assert client.post("/api/auth/login", json={"email": "owner@example.com", "password": "wrong-pass-1"}).status_code == 401
    assert client.post("/api/auth/logout", headers=auth(login.json()["session"])).status_code == 200
    assert client.get("/api/me", headers=auth(login.json()["session"])).status_code == 401


def test_org_project_key_lifecycle_and_separation(client):
    owner = signup(client)
    headers = auth(owner["session"])
    project = client.post(f'/api/orgs/{owner["organization"]["id"]}/projects',
                          json={"name": "Shop Agent"}, headers=headers).json()
    assert "secret" in project["credential"]
    secret = project["credential"]["secret"]
    assert secret.startswith("tvk_")
    listed = client.get(f'/api/projects/{project["id"]}/credentials', headers=headers).json()
    assert listed[0]["prefix"] == secret[:12]
    assert "secret" not in listed[0]
    # Ingest-only key cannot read customer data.
    ingest_headers = {"Authorization": f"Bearer {secret}"}
    assert client.post("/v1/events", json={"events": [event()]} , headers=ingest_headers).status_code == 200
    assert client.get("/api/conversations", params={"project_id": project["id"]},
                      headers=ingest_headers).status_code == 401
    assert client.get("/api/overview", params={"project_id": project["id"]}, headers=headers).status_code == 200
    # Revoked key fails.
    creds = client.get(f'/api/projects/{project["id"]}/credentials', headers=headers).json()
    assert client.post(f'/api/credentials/{creds[0]["id"]}/revoke', headers=headers).status_code == 200
    assert client.post("/v1/events", json={"events": [event(id="e-2")]}, headers=ingest_headers).status_code == 401


def test_cross_organization_access_fails(client):
    first = signup(client, "a@example.com")
    second = signup(client, "b@example.com")
    project = client.post(f'/api/orgs/{first["organization"]["id"]}/projects',
                          json={"name": "Shop"}, headers=auth(first["session"])).json()
    other = auth(second["session"])
    assert client.get("/api/overview", params={"project_id": project["id"]}, headers=other).status_code == 404
    assert client.get("/api/conversations", params={"project_id": project["id"]}, headers=other).status_code == 404
    assert client.get("/api/jobs", params={"project_id": project["id"]}, headers=other).status_code == 404
    assert client.get("/api/projects", headers=other).status_code in (200, 404)


def test_viewer_cannot_mutate(client):
    owner = signup(client, "owner2@example.com")
    member = signup(client, "viewer@example.com")
    headers = auth(owner["session"])
    client.post(f'/api/orgs/{owner["organization"]["id"]}/members',
                json={"email": "viewer@example.com", "role": "viewer"}, headers=headers)
    project = client.post(f'/api/orgs/{owner["organization"]["id"]}/projects',
                          json={"name": "Shop"}, headers=headers).json()
    viewer_headers = auth(member["session"])
    assert client.get("/api/overview", params={"project_id": project["id"]}, headers=viewer_headers).status_code == 200
    assert client.post(f'/api/projects/{project["id"]}/credentials', json={},
                       headers=viewer_headers).status_code in (403, 404, 422)
    assert client.patch(f'/api/projects/{project["id"]}/capture', json={"retention_days": 7},
                        headers=viewer_headers).status_code in (403, 404)


def test_ack_survives_worker_failure_and_retry_counts_once(client, settings):
    owner = signup(client, "w@example.com")
    headers = auth(owner["session"])
    project = client.post(f'/api/orgs/{owner["organization"]["id"]}/projects',
                          json={"name": "Shop"}, headers=headers).json()
    ingest_headers = {"Authorization": f'Bearer {project["credential"]["secret"]}'}
    # Simulate worker failure: ack without processing.
    stalled = create_app(replace(settings, inline_process=False))
    with TestClient(stalled) as worker_down:
        response = worker_down.post("/v1/events", json={"events": [event(), event(id="e-2")]},
                                    headers=ingest_headers)
        assert response.json() == {"accepted": 2, "duplicates": 0}
        # Nothing materialized yet, but jobs are durable.
        assert worker_down.get("/api/overview", params={"project_id": project["id"]},
                               headers=headers).json()["metrics"]["messages"] == 0
    # Worker restarts: the same app processes pending jobs; counts appear once.
    assert client.post("/v1/events", json={"events": [event(), event(id="e-2")]},
                       headers=ingest_headers).json() == {"accepted": 0, "duplicates": 2}
    assert client.get("/api/overview", params={"project_id": project["id"]},
                      headers=headers).json()["metrics"]["messages"] == 2
    usage = client.get(f'/api/projects/{project["id"]}/usage', headers=headers).json()
    assert usage["usage_events"] == 2
    jobs = client.get("/api/jobs", params={"project_id": project["id"]}, headers=headers).json()
    assert jobs["jobs"]["processed"] == 2
    assert jobs["usage_events"] == 2


def test_otlp_nested_and_out_of_order(client):
    import time
    owner = signup(client, "o@example.com")
    headers = auth(owner["session"])
    project = client.post(f'/api/orgs/{owner["organization"]["id"]}/projects',
                          json={"name": "Shop"}, headers=headers).json()
    ingest_headers = {"Authorization": f'Bearer {project["credential"]["secret"]}'}
    now_ns = time.time_ns()
    start = str(now_ns - 2_000_000_000)
    mid = str(now_ns - 400_000_000)
    end = str(now_ns)
    body = {"resourceSpans": [{"scopeSpans": [{"spans": [
        {"traceId": "abc", "spanId": "child", "parentSpanId": "parent", "name": "search_plan_policy",
         "kind": 3, "startTimeUnixNano": mid, "endTimeUnixNano": end,
         "status": {"code": 1},
         "attributes": [{"key": "tervik.conversation.id", "value": {"stringValue": "conv-1"}}]},
        {"traceId": "abc", "spanId": "parent", "name": "supportAgent", "kind": 2,
         "startTimeUnixNano": start, "endTimeUnixNano": mid,
         "status": {"code": 2, "message": "bad tool result"},
         "attributes": [{"key": "tervik.conversation.id", "value": {"stringValue": "conv-1"}}]},
    ]}]}]}
    response = client.post("/v1/otlp/traces", json=body, headers=ingest_headers)
    assert response.json() == {"accepted": 2, "duplicates": 0}, response.text
    detail = client.get("/api/conversations", params={"project_id": project["id"]}, headers=headers).json()
    assert len(detail) == 1
    assert client.post("/v1/otlp/traces", json=body, headers=ingest_headers).json() == {"accepted": 0, "duplicates": 2}


def test_redaction_and_retention(client):
    owner = signup(client, "r@example.com")
    headers = auth(owner["session"])
    project = client.post(f'/api/orgs/{owner["organization"]["id"]}/projects',
                          json={"name": "Shop"}, headers=headers).json()
    pid = project["id"]
    assert client.patch(f"/api/projects/{pid}/capture",
                        json={"redact_keys": ["super-secret-org"], "retention_days": 30},
                        headers=headers).status_code == 200
    ingest_headers = {"Authorization": f'Bearer {project["credential"]["secret"]}'}
    assert client.post("/v1/events", json={"events": [
        event(id="s-1", content="sk-live-abcdefgh12345678 and super-secret-org here")]},
        headers=ingest_headers).status_code == 200
    convs = client.get("/api/conversations", params={"project_id": pid}, headers=headers).json()
    assert "[redacted]" in convs[0]["preview"]
    assert "super-secret-org" not in convs[0]["preview"]
    assert client.post(f"/api/projects/{pid}/retention/run", headers=headers).status_code == 200


def test_failed_job_visible_and_replayable(client, settings):
    owner = signup(client, "f@example.com")
    headers = auth(owner["session"])
    project = client.post(f'/api/orgs/{owner["organization"]["id"]}/projects',
                          json={"name": "Shop"}, headers=headers).json()
    ingest_headers = {"Authorization": f'Bearer {project["credential"]["secret"]}'}
    assert client.post("/v1/events", json={"events": [event()]}, headers=ingest_headers).status_code == 200
    jobs = client.get("/api/jobs", params={"project_id": project["id"]}, headers=headers).json()
    assert jobs["jobs"]["processed"] == 1
    assert jobs["recent"][0]["error_code"] is None
    assert "content" not in jobs["recent"][0]
