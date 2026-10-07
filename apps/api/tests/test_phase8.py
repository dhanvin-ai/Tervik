"""Phase 8 gate: datasets from findings, reviewed runs, replay comparison."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path / 'phase8.db'}")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def project(client, name="Eval"):
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def seed(client, p):
    now = datetime.now(timezone.utc)
    events = [
        {"id": "u1", "conversation_id": "fail-1", "role": "user", "content": "Refund my order",
         "timestamp": (now - timedelta(hours=2)).isoformat()},
        {"id": "t1", "conversation_id": "fail-1", "role": "tool", "content": "refund ok",
         "status": "success", "name": "refund_tool", "trace_id": "t", "span_id": "s1",
         "timestamp": (now - timedelta(hours=2)).isoformat()},
        {"id": "a1", "conversation_id": "fail-1", "role": "assistant", "content": "All done, refund processed!",
         "trace_id": "other", "span_id": "s2",
         "timestamp": (now - timedelta(hours=1, minutes=50)).isoformat()},
        {"id": "u2", "conversation_id": "ok-1", "role": "user", "content": "Thanks, bye",
         "timestamp": (now - timedelta(hours=1)).isoformat()},
        {"id": "a2", "conversation_id": "ok-1", "role": "assistant", "content": "Bye!",
         "timestamp": (now - timedelta(minutes=50)).isoformat()},
    ]
    assert client.post("/v1/events", json={"events": events},
                       headers={"Authorization": f'Bearer {p["api_key"]}'}).status_code == 200


BASELINE = {"name": "baseline", "version": "v1", "tools_plan": [],
            "response_template": "We got your message about {input}."}
CANDIDATE = {"name": "candidate", "version": "v2",
             "tools_plan": [{"name": "refund_tool", "args": {}, "optional": True}],
             "response_template": "Checked records: {tools}."}


def test_dataset_from_findings_review_and_run(client):
    p = project(client)
    seed(client, p)
    built = client.post(f'/api/projects/{p["id"]}/datasets/from-findings', json={
        "name": "Refund regressions", "signal_kinds": ["correction", "frustration",
                                                       "unsupported_claim", "tool_error"],
        "include_controls": True, "limit": 20}).json()
    assert built["status"] == "draft" and built["case_count"] >= 2
    kinds = {c["id"].split("-")[0] for c in built["cases"]}
    assert "finding" in kinds and "control" in kinds
    # Draft datasets cannot run.
    assert client.post(f'/api/datasets/{built["id"]}/runs',
                       json={"baseline": BASELINE, "candidate": CANDIDATE}).status_code == 422
    assert client.patch(f'/api/datasets/{built["id"]}',
                        json={"status": "reviewed"}).json()["status"] == "reviewed"
    run = client.post(f'/api/datasets/{built["id"]}/runs',
                      json={"baseline": BASELINE, "candidate": CANDIDATE,
                            "repeats": 2}).json()
    results = run["results"]
    assert results["reproducible"] is True and results["repeats"] == 2
    assert results["cases"] == built["case_count"]
    assert results["candidate_pass"] >= results["baseline_pass"]
    assert results["regressed"] == []
    assert client.get(f'/api/datasets/{built["id"]}/runs').json()[0]["id"] == run["id"]


def test_replay_isolation_and_regression_caught(client):
    p = project(client)
    dataset = client.post(f'/api/projects/{p["id"]}/datasets', json={
        "name": "Isolation", "cases": [{
            "id": "c1", "input": "Do the thing",
            "tools": [{"name": "real_tool", "recorded_output": "ok"}],
            "expected": {"tools_called": ["real_tool"],
                         "response_contains": "done"}}]}).json()
    client.patch(f'/api/datasets/{dataset["id"]}', json={"status": "approved"})
    run = client.post(f'/api/datasets/{dataset["id"]}/runs', json={
        "baseline": {"name": "b", "version": "1", "tools_plan": [{"name": "real_tool"}],
                     "response_template": "done via {tools}."},
        "candidate": {"name": "c", "version": "2", "tools_plan": [{"name": "ghost_tool"}],
                      "response_template": "done."}}).json()
    results = run["results"]
    assert results["baseline_pass"] == 1 and results["candidate_pass"] == 0
    assert results["regressed"] == ["c1"] and results["verdict"] == "regressed"
    detail = results["details"][0]["candidate"]
    assert detail["missing_tools"] == ["ghost_tool"]
    assert detail["passed"] is False


def test_org_eval_requires_review_roles(client):
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
    assert client.post(f'/api/projects/{project["id"]}/datasets',
                       json={"name": "x", "cases": [{"id": "c", "input": "hi"}]},
                       headers=viewer).status_code in (403, 404)
    dataset = client.post(f'/api/projects/{project["id"]}/datasets',
                          json={"name": "x", "cases": [{"id": "c", "input": "hi"}]},
                          headers=headers).json()
    assert client.get(f'/api/projects/{project["id"]}/datasets', headers=viewer).status_code == 200
