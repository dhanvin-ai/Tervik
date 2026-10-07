"""Phase 5 API tests: new detectors, versions, behavior rules."""
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path / 'phase5.db'}")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def project(client, name="Detect"):
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def ingest(client, p, events):
    return client.post("/v1/events", json={"events": events},
                       headers={"Authorization": f'Bearer {p["api_key"]}'})


def event(id="e-1", conversation_id="c-1", **values):
    return {"id": id, "conversation_id": conversation_id, "role": "user",
            "content": "Hello", **values}


def kinds(client, p):
    return {row["kind"] for row in client.get("/api/clusters", params={"project_id": p["id"]}).json()}


def test_timeout_unresolved_and_claim_detectors(client):
    p = project(client)
    assert ingest(client, p, [
        event("t1", role="tool", status="error", name="billing", content="Request timed out after 2000 ms"),
        event("u1", conversation_id="c-2", content="That didn't work."),
        event("a1", conversation_id="c-3", role="assistant", content="I've sent the refund.", trace_id="t"),
    ]).status_code == 200
    assert kinds(client, p) == {"tool_timeout", "unresolved", "unsupported_claim"}
    detail = client.get("/api/conversations", params={"project_id": p["id"]}).json()
    flagged = [c for c in detail if c["status"] == "flagged"]
    assert len(flagged) == 3
    conv = client.get(f'/api/conversations/{flagged[0]["id"]}').json()
    assert conv["signals"][0]["detector_version"] == "5.0.0"
    assert conv["signals"][0]["rule_version"] == "5.0.0"


def test_supported_claim_and_abstention_stay_quiet(client):
    p = project(client)
    assert ingest(client, p, [
        event("tool1", role="tool", status="success", name="refund", content="ok",
              trace_id="t", span_id="s1"),
        event("ok1", role="assistant", content="I've sent the refund.", trace_id="t", span_id="s2"),
        event("tool2", conversation_id="c-2", role="tool", status="success", name="search",
              content="found", trace_id="other", span_id="s3"),
        event("abs1", conversation_id="c-2", role="assistant", content="All done!", span_id="s4"),
    ]).status_code == 200
    assert kinds(client, p) == set()
    assert client.get("/api/overview", params={"project_id": p["id"]}).json()["metrics"]["failure_rate"] == 0


def test_behavior_rules_crud_and_violations(client):
    p = project(client)
    assert client.get(f'/api/projects/{p["id"]}/rules').json() == []
    assert client.post(f'/api/projects/{p["id"]}/rules',
                       json={"name": "x", "kind": "forbidden_phrase"}).status_code == 422
    assert client.post(f'/api/projects/{p["id"]}/rules',
                       json={"name": "x", "kind": "forbidden_phrase", "pattern": "[bad"}).status_code == 422
    rule = client.post(f'/api/projects/{p["id"]}/rules',
                       json={"name": "no guarantees", "kind": "forbidden_phrase",
                             "pattern": "guarantee\\w*"}).json()
    assert rule["version"] == "1" and rule["enabled"] is True
    required = client.post(f'/api/projects/{p["id"]}/rules',
                           json={"name": "needs lookup", "kind": "required_tool",
                                 "tool": "lookup_policy"}).json()
    assert ingest(client, p, [
        event("a1", role="assistant", content="We guarantee approval."),
        event("a2", conversation_id="c-2", role="assistant", content="Three projects max."),
    ]).status_code == 200
    rows = client.get("/api/clusters", params={"project_id": p["id"]}).json()
    assert [r["kind"] for r in rows] == ["rule_violation"]
    assert client.patch(f'/api/rules/{required["id"]}', json={"enabled": False}).status_code == 200
    assert {r["kind"] for r in client.get("/api/clusters", params={"project_id": p["id"]}).json()} == {"rule_violation"}
    assert client.delete(f'/api/rules/{rule["id"]}').status_code == 200
    assert len(client.get(f'/api/projects/{p["id"]}/rules').json()) == 1


def test_org_rules_require_admin_and_audit(client):
    owner = client.post("/api/auth/signup",
                        json={"email": "o@example.com", "password": "password-123"}).json()
    headers = {"Authorization": f'Bearer {owner["session"]}'}
    member = client.post("/api/auth/signup",
                         json={"email": "m@example.com", "password": "password-123"}).json()
    client.post(f'/api/orgs/{owner["organization"]["id"]}/members',
                json={"email": "m@example.com", "role": "viewer"}, headers=headers)
    project = client.post(f'/api/orgs/{owner["organization"]["id"]}/projects',
                          json={"name": "Shop"}, headers=headers).json()
    viewer = {"Authorization": f'Bearer {member["session"]}'}
    assert client.post(f'/api/projects/{project["id"]}/rules',
                       json={"name": "r", "kind": "required_tool", "tool": "t"},
                       headers=viewer).status_code in (403, 404)
    rule = client.post(f'/api/projects/{project["id"]}/rules',
                       json={"name": "r", "kind": "required_tool", "tool": "t"},
                       headers=headers).json()
    assert client.get(f'/api/projects/{project["id"]}/rules', headers=viewer).status_code == 200
    entries = client.get(f'/api/orgs/{owner["organization"]["id"]}/audit', headers=headers).json()
    assert any(e["action"] == "rule.create" and e["resource"] == rule["id"] for e in entries)
