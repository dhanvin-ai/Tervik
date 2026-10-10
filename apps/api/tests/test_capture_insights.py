"""Session/event capture API and the operational analytics built on it."""
from dataclasses import replace
from datetime import timedelta
import csv
import io
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Project, utc_now
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path / 'capture.db'}")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def project(client, name="Support Agent"):
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def org(p):
    return {"x-org-id": p["id"]}


def ms(delta=timedelta()):
    return int((utc_now() - delta).timestamp() * 1000)


def start_session(client, p, session_id="s-1", user_id="user-1", **extra):
    body = {"session_id": session_id, "user_data": {"user_id": user_id, **extra.pop("traits", {})}, **extra}
    response = client.post("/api/v1/capture-session", json=body, headers=org(p))
    assert response.status_code == 200, response.text
    return response.json()


def capture(client, p, event_id, session_id="s-1", headers=None, **values):
    body = {"event_id": event_id, "session_id": session_id, "primitive_name": "support-agent",
            "args": "", "result": "", **values}
    response = client.post("/api/v1/capture-event", json=body, headers=headers or org(p))
    assert response.status_code == 200, response.text
    return response.json()


def conversation_of(client, p, session_id="s-1"):
    rows = client.get("/api/conversations", params={"project_id": p["id"], "range": "7d"}).json()
    events = client.get(f'/api/projects/{p["id"]}/events', params={"conversation_id": session_id}).json()["events"]
    target = events[0]["conversation_id"]
    row = next(r for r in rows if r["id"] == target)
    return row, client.get(f'/api/conversations/{target}').json()


# ---- capture API ----

def test_capture_auth_accepts_project_id_and_ingest_keys(client):
    p = project(client)
    body = {"session_id": "s-1", "user_data": {"user_id": "u-1"}}
    assert client.post("/api/v1/capture-session", json=body).status_code == 401
    assert client.post("/api/v1/capture-session", json=body, headers={"x-org-id": "missing"}).status_code == 401
    assert client.post("/api/v1/capture-session", json=body, headers=org(p)).json() == {"session_id": "s-1"}
    bearer = {"Authorization": f'Bearer {p["api_key"]}'}
    assert client.post("/api/v1/capture-session", json=body, headers=bearer).status_code == 200
    assert client.post("/api/v1/capture-session", json=body, headers={"x-api-key": p["api_key"]}).status_code == 200
    assert client.post("/api/v1/capture-session", json=body, headers={"x-api-key": "nope"}).status_code == 401


def test_public_ingest_can_be_turned_off(client):
    p = project(client)
    with client.app.state.sessions.begin() as session:
        row = session.get(Project, p["id"])
        row.settings = {**(row.settings or {}), "public_ingest": False}
    body = {"session_id": "s-1", "user_data": {"user_id": "u-1"}}
    assert client.post("/api/v1/capture-session", json=body, headers=org(p)).status_code == 401
    assert client.post("/api/v1/capture-session", json=body, headers={"x-api-key": p["api_key"]}).status_code == 200


def test_capture_is_exempt_from_admin_token_but_dashboard_is_not(settings):
    admin = {"Authorization": "Bearer admin-secret"}
    with TestClient(create_app(replace(settings, admin_token="admin-secret", demo_enabled=False))) as client:
        p = client.post("/api/projects", json={"name": "Agent"}, headers=admin).json()
        assert client.post("/api/v1/capture-session", json={"session_id": "s", "user_data": {"user_id": "u"}},
                           headers=org(p)).status_code == 200
        assert client.get(f'/api/projects/{p["id"]}/summary').status_code == 401
        assert client.get(f'/api/projects/{p["id"]}/summary', headers=admin).status_code == 200


def test_capture_validation(client):
    p = project(client)
    bad_sessions = [{"session_id": "s", "user_data": {}}, {"session_id": " ", "user_data": {"user_id": "u"}},
                    {"session_id": "s", "user_data": {"user_id": "u", **{f"k{i}": "v" for i in range(60)}}},
                    {"session_id": "s", "user_data": {"user_id": "u"}, "timestamp": "soon"}]
    for body in bad_sessions:
        assert client.post("/api/v1/capture-session", json=body, headers=org(p)).status_code == 422, body
    base = {"event_id": "e", "session_id": "s", "primitive_name": "agent"}
    assert client.post("/api/v1/capture-event", json={**base, "primitive_name": ""}, headers=org(p)).status_code == 422
    assert client.post("/api/v1/capture-event", json={**base, "args": "x" * 32_001}, headers=org(p)).status_code == 422
    assert client.post("/api/v1/capture-event", json={**base, "latency": -1}, headers=org(p)).status_code == 422
    future = int((utc_now() + timedelta(hours=1)).timestamp() * 1000)
    assert client.post("/api/v1/capture-event", json={**base, "timestamp": future}, headers=org(p)).status_code == 422


def test_turn_pair_and_tool_call_map_to_one_conversation(client):
    p = project(client)
    start_session(client, p, traits={"plan": "pro"}, metadata={"language": "en"}, client_config="sdk-test")
    capture(client, p, "turn-1", args="Where is my order 1042?", result="It ships tomorrow.",
            latency=1200, timestamp=ms(timedelta(minutes=5)), metadata={"model": "gpt-4.1", "tokens": "150", "cost": "0.002"})
    capture(client, p, "tool-1", parent_id="turn-1", primitive_name="orders.lookup",
            args={"order_id": 1042}, result={"status": "shipped"}, latency=300, timestamp=ms(timedelta(minutes=5)))
    row, detail = conversation_of(client, p)
    assert row["user_id"] == "user-1" and row["message_count"] == 3
    roles = [(m["role"], m["name"]) for m in detail["messages"]]
    assert ("user", None) in roles and ("assistant", "support-agent") in roles and ("tool", "orders.lookup") in roles
    assistant = next(m for m in detail["messages"] if m["role"] == "assistant")
    assert assistant["latency_ms"] == 1200 and assistant["model"] == "gpt-4.1"
    assert assistant["tokens"] == 150 and assistant["cost_usd"] == 0.002
    tool = next(m for m in detail["messages"] if m["role"] == "tool")
    assert tool["parent_span_id"] == "turn-1" and tool["trace_id"] == "turn-1"
    assert tool["metadata"]["input"] == '{"order_id": 1042}'
    assert detail["session"] == {"session_id": "s-1", "user_id": "user-1", "user_traits": {"plan": "pro"},
                                 "metadata": {"language": "en"}, "client_config": "sdk-test",
                                 "started_at": detail["session"]["started_at"]}
    spans = {span["id"]: span for span in detail["spans"]}
    assert spans["tool-1"]["parent_id"] == "turn-1"


def test_capture_is_idempotent_and_backfills_late_sessions(client):
    p = project(client)
    capture(client, p, "turn-1", session_id="late", args="Hello there", result="Hi!")
    capture(client, p, "turn-1", session_id="late", args="Hello there", result="Hi!")
    events = client.get(f'/api/projects/{p["id"]}/events', params={"conversation_id": "late"}).json()
    assert events["total"] == 2 and all(e["user_id"] is None for e in events["events"])
    start_session(client, p, session_id="late", user_id="user-9")
    events = client.get(f'/api/projects/{p["id"]}/events', params={"conversation_id": "late"}).json()
    assert {e["user_id"] for e in events["events"]} == {"user-9"}


def test_children_captured_before_parent_join_its_trace(client):
    p = project(client)
    start_session(client, p)
    # SDKs finish (and send) inner work first: grandchild, child, then the turn.
    capture(client, p, "inner", parent_id="outer", primitive_name="email.send", result="sent", timestamp=ms(timedelta(seconds=20)))
    capture(client, p, "outer", parent_id="turn-1", primitive_name="email.compose", result="drafted", timestamp=ms(timedelta(seconds=25)))
    capture(client, p, "turn-1", args="Email the receipt", result="I've sent the email with your receipt.",
            latency=10_000, timestamp=ms(timedelta(seconds=30)))
    _, detail = conversation_of(client, p)
    traces = {m["id"]: m["trace_id"] for m in detail["messages"]}
    assert traces["inner"] == traces["outer"] == traces["turn-1:output"] == "turn-1"
    assert "unsupported_claim" not in detail["tags"]


def test_claims_without_tool_evidence_and_failed_tools_are_detected(client):
    p = project(client)
    start_session(client, p)
    capture(client, p, "turn-1", args="Refund my order", result="I've refunded the order.", latency=900)
    start_session(client, p, session_id="s-2", user_id="user-2")
    capture(client, p, "turn-2", session_id="s-2", args="Book a table", result="Something went wrong.", success=False)
    capture(client, p, "tool-2", session_id="s-2", parent_id="turn-2", primitive_name="booking.create",
            result="Error: upstream timed out after 30s", success=False, latency=30_000)
    clusters = client.get("/api/clusters", params={"project_id": p["id"]}).json()
    kinds = {c["kind"] for c in clusters}
    assert {"unsupported_claim", "tool_timeout"} <= kinds


# ---- analytics ----

@pytest.fixture
def populated(client):
    p = project(client)
    start_session(client, p, session_id="s-1", user_id="ana", traits={"plan": "pro"}, metadata={"surface": "web"})
    start_session(client, p, session_id="s-2", user_id="ben", traits={"plan": "free"}, metadata={"surface": "app"})
    start_session(client, p, session_id="s-3", user_id="ana", metadata={"surface": "web"})
    day = timedelta(days=1, hours=1)
    capture(client, p, "t1", "s-1", args="Track order 1", result="On its way", latency=800,
            timestamp=ms(2 * day), metadata={"agent_version": "v1"})
    capture(client, p, "c1", "s-1", parent_id="t1", primitive_name="orders.lookup", result="{}",
            latency=100, timestamp=ms(2 * day))
    capture(client, p, "t2", "s-2", args="Cancel order 22", result="Could not cancel", latency=1500,
            success=False, timestamp=ms(day), metadata={"agent_version": "v2"})
    capture(client, p, "c2", "s-2", parent_id="t2", primitive_name="orders.cancel",
            result="=HYPERLINK(\"http://x\")\nOrder 22 not found", latency=400, success=False, timestamp=ms(day))
    capture(client, p, "c3", "s-2", parent_id="t2", primitive_name="orders.cancel",
            result="Order 9137 not found", latency=600, success=False, timestamp=ms(day))
    capture(client, p, "t3", "s-3", args="That is wrong, I meant order 3", result="Sorry, checking order 3",
            latency=700, timestamp=ms(timedelta(hours=2)), metadata={"agent_version": "v2"})
    capture(client, p, "c4", "s-3", parent_id="t3", primitive_name="orders.lookup", result="{}",
            latency=300, timestamp=ms(timedelta(hours=2)))
    return p


def test_summary_counts_operations_not_messages(client, populated):
    p = populated
    body = client.get(f'/api/projects/{p["id"]}/summary', params={"range": "7d"}).json()
    assert body["total_calls"] == 7 and body["turns"] == 3 and body["tool_calls"] == 4
    assert body["total_conversations"] == 3 and body["active_users"] == 2
    assert body["errors"] == 3 and body["success_rate"] == round(100 * 4 / 7, 2)
    assert body["granularity"] == "day" and len(body["timeline"]) == 8
    assert sum(point["calls"] for point in body["timeline"]) == 7
    assert body["agents"] == [{"name": "support-agent", "calls": 3, "errors": 1}]
    hourly = client.get(f'/api/projects/{p["id"]}/summary', params={"range": "24h"}).json()
    assert hourly["granularity"] == "hour" and hourly["total_calls"] == 2
    assert client.get(f'/api/projects/{p["id"]}/summary', params={"range": "all"}).json()["total_calls"] == 7
    assert client.get(f'/api/projects/{p["id"]}/summary', params={"range": "2w"}).status_code == 422


def test_tool_stats_and_error_distribution(client, populated):
    body = client.get(f'/api/projects/{populated["id"]}/tools').json()
    tools = {row["name"]: row for row in body["tools"]}
    assert tools["orders.lookup"]["calls"] == 2 and tools["orders.lookup"]["success_rate"] == 100
    cancel = tools["orders.cancel"]
    assert cancel["errors"] == 2 and cancel["success_rate"] == 0
    assert cancel["avg_latency_ms"] == 500 and cancel["p50_latency_ms"] == 400 and cancel["p95_latency_ms"] == 600
    # Order numbers differ but the failure is the same, so it groups once.
    assert any(group["count"] == 1 for group in cancel["top_errors"])
    assert body["error_distribution"] == [{"name": "orders.cancel", "errors": 2, "share": 100.0}]


def test_event_log_filters_pages_and_exports(client, populated):
    url = f'/api/projects/{populated["id"]}/events'
    page = client.get(url, params={"page_size": 4}).json()
    assert page["total"] == 10 and page["total_pages"] == 3 and page["has_more"] and len(page["events"]) == 4
    assert client.get(url, params={"event_type": "tool_call"}).json()["total"] == 4
    assert client.get(url, params={"status": "error"}).json()["total"] == 3
    assert client.get(url, params={"metadata_key": "agent_version", "metadata_value": "v2"}).json()["total"] == 4
    assert client.get(url, params={"search": "cancel"}).json()["total"] >= 2
    assert client.get(url, params={"user_id": "ana"}).json()["total"] == 6
    oldest = client.get(url, params={"sort": "oldest"}).json()["events"][0]
    assert oldest["session_id"] == "s-1" and "input" not in oldest["metadata"]
    exported = client.get(f"{url}/export", params={"status": "error"})
    assert exported.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(exported.text)))
    assert rows[0][0] == "id" and len(rows) == 4
    assert any(row[-1].startswith("'=HYPERLINK") for row in rows[1:])


def test_event_detail_links_pair_parent_children_and_session(client, populated):
    url = f'/api/projects/{populated["id"]}/events'
    turn = client.get(f"{url}/t2:output").json()
    assert turn["event"]["metadata"]["input"] == "Cancel order 22"
    assert [e["id"] for e in turn["pair"]] == ["t2:input"]
    assert {e["id"] for e in turn["children"]} == {"c2", "c3"}
    assert turn["session"]["user_id"] == "ben" and turn["session"]["metadata"] == {"surface": "app"}
    tool = client.get(f"{url}/c2").json()
    assert tool["parent"]["id"] == "t2:output" and tool["children"] == []
    assert client.get(f"{url}/missing").status_code == 404


def test_errors_metadata_users_groups_and_search(client, populated):
    base = f'/api/projects/{populated["id"]}'
    errors = client.get(f"{base}/errors").json()
    assert errors["total"] == 3 and errors["by_name"][0] == {"name": "orders.cancel", "count": 2}
    keys = {row["key"]: row for row in client.get(f"{base}/metadata").json()["keys"]}
    assert keys["agent_version"]["source"] == "event" and keys["surface"]["source"] == "session"
    assert keys["plan"]["source"] == "user" and "capture_event_id" not in keys
    surface = client.get(f"{base}/metadata", params={"key": "surface"}).json()
    assert {v["value"]: v["conversations"] for v in surface["values"]} == {"web": 2, "app": 1}
    users = client.get(f"{base}/users").json()
    ana = next(u for u in users["users"] if u["user_id"] == "ana")
    assert ana["conversations"] == 2 and ana["traits"] == {"plan": "pro"}
    assert "Users are correcting the agent" in ana["problem_labels"]
    assert client.get(f"{base}/users", params={"search": "free"}).json()["users"][0]["user_id"] == "ben"
    groups = client.get(f"{base}/groups", params={"key": "plan"}).json()
    assert {g["value"]: g["conversations"] for g in groups["groups"]} == {"pro": 2, "free": 1}
    found = client.get(f"{base}/search", params={"q": "order 22"}).json()
    assert found["total"] >= 1 and "order 22" in found["results"][0]["snippet"].casefold()
    assert client.get(f"{base}/search", params={"q": "x"}).status_code == 422


def test_ingest_keys_cannot_read_analytics(client, populated):
    headers = {"Authorization": f'Bearer {populated["api_key"]}'}
    assert client.get(f'/api/projects/{populated["id"]}/summary', headers=headers).status_code == 401
    assert client.get(f'/api/projects/{populated["id"]}/events', headers=headers).status_code == 401
    assert client.get("/api/projects/missing/summary").status_code == 404


def test_analytics_are_org_scoped(client):
    owner = client.post("/api/auth/signup", json={"email": "a@example.com", "password": "password-123"}).json()
    other = client.post("/api/auth/signup", json={"email": "b@example.com", "password": "password-123"}).json()
    created = client.post(f'/api/orgs/{owner["organization"]["id"]}/projects', json={"name": "Shop"},
                          headers={"Authorization": f'Bearer {owner["session"]}'}).json()
    url = f'/api/projects/{created["id"]}/summary'
    assert client.get(url, headers={"Authorization": f'Bearer {owner["session"]}'}).status_code == 200
    assert client.get(url, headers={"Authorization": f'Bearer {other["session"]}'}).status_code == 404
