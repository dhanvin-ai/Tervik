"""Phase 9 gate: one issue completes propose→deploy→monitor→resolve, plus rollback."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path / 'phase9.db'}")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def project(client, name="Fix"):
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def seed(client, p):
    now = datetime.now(timezone.utc)
    events = [
        {"id": "u1", "conversation_id": "c-1", "role": "user", "content": "Refund my order",
         "timestamp": (now - timedelta(days=2)).isoformat()},
        {"id": "a1", "conversation_id": "c-1", "role": "assistant",
         "content": "All done, refund processed!", "trace_id": "t",
         "timestamp": (now - timedelta(days=2)).isoformat()},
    ]
    assert client.post("/v1/events", json={"events": events},
                       headers={"Authorization": f'Bearer {p["api_key"]}'}).status_code == 200


def transition(client, imp_id, to, status=200):
    response = client.post(f"/api/improvements/{imp_id}/transition", json={"to": to})
    assert response.status_code == status, response.text
    return response.json()


def test_full_lifecycle_to_resolved(client):
    p = project(client)
    seed(client, p)
    imp = client.post(f'/api/projects/{p["id"]}/improvements', json={
        "signal_kind": "unsupported_claim", "tool": "refund_tool",
        "evidence_event_id": "a1"}).json()
    assert imp["state"] == "proposed"
    assert "refund_tool" in imp["candidate_diff"] and imp["uncertainty"]
    assert imp["evidence"][0]["event_id"] == "a1"
    # Guards: no skipping, no deployment before approval.
    transition(client, imp["id"], "deployed", 422)
    transition(client, imp["id"], "evaluating", 422)
    transition(client, imp["id"], "investigating")
    transition(client, imp["id"], "candidate_ready")
    transition(client, imp["id"], "evaluating", 422)  # no eval run attached
    # Verify via a reviewed evaluation run.
    dataset = client.post(f'/api/projects/{p["id"]}/datasets/from-findings', json={
        "name": "claims", "signal_kinds": ["unsupported_claim"],
        "include_controls": False, "limit": 10}).json()
    client.patch(f'/api/datasets/{dataset["id"]}', json={"status": "reviewed"})
    run = client.post(f'/api/datasets/{dataset["id"]}/runs', json={
        "baseline": {"name": "b", "version": "1", "tools_plan": [],
                     "response_template": "We got your message about {input}."},
        "candidate": {"name": "c", "version": "2",
                      "tools_plan": [{"name": "refund_tool", "optional": True}],
                      "response_template": "Checked records: {tools}."}}).json()
    assert run["results"]["verdict"] in ("improved", "no_change")
    assert run["results"]["regressed"] == []
    assert client.post(f'/api/improvements/{imp["id"]}/eval',
                       json={"eval_run_id": run["id"]}).status_code == 200
    transition(client, imp["id"], "evaluating")
    transition(client, imp["id"], "awaiting_approval")
    deployed = transition(client, imp["id"], "deployed")
    assert deployed["state"] == "deployed" and deployed["deployed_at"]
    prompts = client.get(f'/api/projects/{p["id"]}/prompts').json()
    assert len(prompts) == 1 and prompts[0]["status"] == "active"
    assert "refund_tool" in client.get(f'/api/improvements/{imp["id"]}').json()["prompts"][0]["content"]
    transition(client, imp["id"], "monitoring")
    measured = client.get(f'/api/improvements/{imp["id"]}/measurements').json()
    assert measured["improvement_id"] == imp["id"] and "status" in measured
    resolved = transition(client, imp["id"], "resolved")
    assert resolved["state"] == "resolved" and "status" in resolved["measurements"]
    transition(client, imp["id"], "deployed", 422)  # terminal state


def test_rollback_restores_prior_prompt(client):
    p = project(client)
    seed(client, p)
    first = client.post(f'/api/projects/{p["id"]}/improvements', json={
        "signal_kind": "tool_error", "tool": "billing"}).json()
    for state in ("investigating", "candidate_ready"):
        transition(client, first["id"], state)
    dataset = client.post(f'/api/projects/{p["id"]}/datasets', json={
        "name": "d", "cases": [{"id": "c1", "input": "hi",
                                "expected": {"response_contains": "hi"}}]}).json()
    client.patch(f'/api/datasets/{dataset["id"]}', json={"status": "approved"})
    run = client.post(f'/api/datasets/{dataset["id"]}/runs', json={
        "baseline": {"name": "b", "version": "1", "tools_plan": [],
                     "response_template": "hi there"},
        "candidate": {"name": "c", "version": "2", "tools_plan": [],
                      "response_template": "hi there!"}}).json()
    assert run["results"]["verdict"] in ("improved", "no_change")
    client.post(f'/api/improvements/{first["id"]}/eval', json={"eval_run_id": run["id"]})
    for state in ("evaluating", "awaiting_approval", "deployed"):
        transition(client, first["id"], state)
    second = client.post(f'/api/projects/{p["id"]}/improvements', json={
        "signal_kind": "tool_error", "tool": "billing"}).json()
    for state in ("investigating", "candidate_ready"):
        transition(client, second["id"], state)
    client.post(f'/api/improvements/{second["id"]}/eval', json={"eval_run_id": run["id"]})
    for state in ("evaluating", "awaiting_approval", "deployed"):
        transition(client, second["id"], state)
    prompts = client.get(f'/api/projects/{p["id"]}/prompts').json()
    assert [pr["status"] for pr in sorted(prompts, key=lambda pr: pr["version"])] == ["superseded", "active"]
    rolled = transition(client, second["id"], "rolled_back")
    assert rolled["state"] == "rolled_back"
    prompts = client.get(f'/api/projects/{p["id"]}/prompts').json()
    by_version = {pr["version"]: pr["status"] for pr in prompts}
    assert by_version[1] == "active" and by_version[2] == "rolled_back"


def test_org_roles_guard_approval(client):
    owner = client.post("/api/auth/signup",
                        json={"email": "o@example.com", "password": "password-123"}).json()
    headers = {"Authorization": f'Bearer {owner["session"]}'}
    member = client.post("/api/auth/signup",
                         json={"email": "m@example.com", "password": "password-123"}).json()
    client.post(f'/api/orgs/{owner["organization"]["id"]}/members',
                json={"email": "m@example.com", "role": "member"}, headers=headers)
    project = client.post(f'/api/orgs/{owner["organization"]["id"]}/projects',
                          json={"name": "Shop"}, headers=headers).json()
    viewer_headers = {"Authorization": f'Bearer {member["session"]}'}
    imp = client.post(f'/api/projects/{project["id"]}/improvements',
                      json={"signal_kind": "correction"}, headers=headers).json()
    assert imp["state"] == "proposed"
    assert client.post(f'/api/improvements/{imp["id"]}/transition', json={"to": "deployed"},
                       headers=viewer_headers).status_code in (403, 422)
    assert client.post(f'/api/improvements/{imp["id"]}/transition', json={"to": "investigating"},
                       headers=viewer_headers).status_code == 200
