"""Read API keys, alerts on intents/violations/tools with Slack and summaries,
plan tiers with rolling usage, and the analytics tools on the MCP server."""
from dataclasses import replace
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading

import pytest
from fastapi.testclient import TestClient

from app.alerts import process_deliveries
from app.config import Settings
from app.db import make_database, utc_now
from app.main import create_app
from test_classification import FakeLLM, reviewer


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path / 'platform.db'}", dashboard_url="https://app.example.com")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        client.app.state.llm = FakeLLM(reviewer)
        yield client


@pytest.fixture
def webhook():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/hook", received
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def project(client, name="Platform"):
    return client.post("/api/projects", json={"name": name}).json()


def capture(client, p, session_id, event_id, args="", result="", minutes_ago=30, **values):
    client.post("/api/v1/capture-session", json={"session_id": session_id, "user_data": {"user_id": f"u-{session_id}"}},
                headers={"x-org-id": p["id"]})
    stamp = int((utc_now() - timedelta(minutes=minutes_ago)).timestamp() * 1000)
    response = client.post("/api/v1/capture-event", headers={"x-org-id": p["id"]}, json={
        "event_id": event_id, "session_id": session_id, "primitive_name": values.pop("name", "agent"),
        "args": args, "result": result, "timestamp": stamp, **values})
    assert response.status_code == 200, response.text
    return response


def deliver(settings):
    _, sessions = make_database(settings.database_url)
    with sessions.begin() as session:
        return process_deliveries(session, settings)


# ---- read API keys ----

def test_api_keys_read_one_project_and_nothing_else(client):
    p, other = project(client), project(client, "Other")
    capture(client, p, "s-1", "t1", "Hello", "Hi")
    capture(client, other, "s-9", "t9", "Elsewhere", "Hi")
    created = client.post(f'/api/projects/{p["id"]}/api-keys', json={"name": "Reporting"}).json()
    assert re.fullmatch(r"tervik_[0-9a-f]{64}", created["secret"]) and created["prefix"] == created["secret"][:14]
    listed = client.get(f'/api/projects/{p["id"]}/api-keys').json()
    assert listed[0]["name"] == "Reporting" and "secret" not in listed[0]
    key = {"x-api-key": created["secret"]}
    assert client.get(f'/api/projects/{p["id"]}/summary', headers=key).json()["total_calls"] == 1
    assert client.get(f'/api/projects/{p["id"]}/events', headers=key).status_code == 200
    assert client.get("/api/overview", params={"project_id": p["id"]}, headers=key).status_code == 200
    assert client.post(f'/api/projects/{p["id"]}/classify', json={}, headers=key).status_code == 200
    other_conversation = client.get(f'/api/projects/{other["id"]}/events').json()["events"][0]["conversation_id"]
    for method, url, params in [("get", f'/api/projects/{other["id"]}/summary', None),
                                ("get", "/api/projects", None), ("get", f'/api/projects/{p["id"]}/key', None),
                                ("get", f'/api/projects/{p["id"]}/api-keys', None),
                                ("get", "/api/overview", {"project_id": other["id"]}), ("get", "/api/overview", None),
                                ("post", f'/api/projects/{p["id"]}/policies', None),
                                ("delete", f'/api/projects/{p["id"]}', None)]:
        response = getattr(client, method)(url, params=params, headers=key) if method != "post" else \
            client.post(url, json={"title": "x"}, headers=key)
        assert response.status_code == 403, (method, url, response.status_code)
    assert client.get(f"/api/conversations/{other_conversation}", headers=key).status_code == 404
    assert client.get(f'/api/projects/{p["id"]}/summary', headers={"x-api-key": "tervik_" + "0" * 64}).status_code == 401
    revoked = client.delete(f'/api/api-keys/{created["id"]}').json()
    assert revoked["revoked_at"]
    assert client.get(f'/api/projects/{p["id"]}/summary', headers=key).status_code == 401


def test_api_keys_work_when_the_dashboard_needs_an_admin_token(settings):
    admin = {"Authorization": "Bearer admin-secret"}
    with TestClient(create_app(replace(settings, admin_token="admin-secret", demo_enabled=False))) as client:
        p = client.post("/api/projects", json={"name": "Agent"}, headers=admin).json()
        secret = client.post(f'/api/projects/{p["id"]}/api-keys', json={"name": "ci"}, headers=admin).json()["secret"]
        assert client.get(f'/api/projects/{p["id"]}/summary').status_code == 401
        assert client.get(f'/api/projects/{p["id"]}/summary', headers={"x-api-key": secret}).status_code == 200
        assert client.post(f'/api/projects/{p["id"]}/api-keys', json={"name": "x"}).status_code == 401


# ---- alerts ----

def test_intent_violation_and_tool_alerts_fire_with_examples(client, settings, webhook):
    url, received = webhook
    p = project(client)
    base = f'/api/projects/{p["id"]}'
    intent = client.post(f"{base}/intents", json={"name": "Get a refund", "description": "Wants money back."}).json()
    policy = client.post(f"{base}/policies", json={"title": "Never reveal account numbers"}).json()
    capture(client, p, "s-1", "t1", "I want a refund for order 7", "Refunded to account number is 4400123456.", latency=300)
    capture(client, p, "s-1", "c1", result="Error: card declined", parent_id="t1", name="payments.refund", success=False)
    client.post(f"{base}/classify", json={})
    channel = [{"type": "webhook", "target": url}]
    common = {"kind": "threshold", "threshold": 1, "window_hours": 24, "min_samples": 1, "channels": channel}
    rules = [client.post(f"{base}/alerts", json={**common, "name": name, **extra}) for name, extra in [
        ("Refunds", {"metric": "intent", "target": intent["id"]}),
        ("Leaks", {"metric": "violation", "target": policy["id"]}),
        ("Refund tool", {"metric": "tool_errors", "target": "payments.refund"}),
        ("Error rate", {"metric": "error_rate", "threshold": 25}),
        ("Volume", {"metric": "conversations", "threshold": 5})]]
    assert all(r.status_code == 201 for r in rules), [r.text for r in rules]
    assert rules[0].json()["metric"] == "intent" and rules[0].json()["target"] == intent["id"]
    results = {r["rule_id"]: r["fired"] for r in client.post(f"{base}/alerts/evaluate").json()["results"]}
    assert [results[r.json()["id"]] for r in rules] == [True, True, True, True, False]
    assert deliver(settings) == (4, 0)
    texts = {item["text"].split("\n", 1)[0]: item["text"] for item in received}
    assert "Refunds: 1 conversations with this intent" in texts
    leak = texts["Leaks: 1 conversations that broke this policy"]
    assert "(Never reveal account numbers)" in leak and "s-1 (u-s-1): I want a refund for order 7" in leak
    assert "https://app.example.com/#overview" in leak
    assert "Refund tool: 1 failed tool calls" in texts and "Error rate: 50.0% of operations failed" in texts
    history = client.get(f'/api/alerts/{rules[1].json()["id"]}/history').json()
    assert len(history) == 1 and history[0]["state"] == "sent"


def test_alert_validation(client):
    base = f'/api/projects/{project(client)["id"]}'
    channel = [{"type": "webhook", "target": "https://example.com/hook"}]
    bad = [{"kind": "threshold", "metric": "intent", "channels": channel},
           {"kind": "threshold", "metric": "intent", "target": "missing", "channels": channel},
           {"kind": "summary", "metric": "tool_errors", "channels": channel},
           {"kind": "threshold", "metric": "suggested_intents", "channels": channel},
           {"kind": "threshold", "metric": "error_rate", "threshold": 150, "channels": channel},
           {"kind": "summary", "channels": [{"type": "slack", "target": "https://example.com/hook"}]},
           {"kind": "summary", "channels": [{"type": "email", "target": "nobody"}]}]
    for body in bad:
        assert client.post(f"{base}/alerts", json={"name": "x", **body}).status_code == 422, body


def test_slack_connect_and_summaries(client, settings, webhook):
    url, received = webhook
    p = project(client)
    base = f'/api/projects/{p["id"]}'
    slack = "https://hooks.slack.com/services/T000/B000/XXXX"
    first = client.post(f"{base}/alerts/slack", json={"webhook_url": slack}).json()["alerts"]
    again = client.post(f"{base}/alerts/slack", json={"webhook_url": slack}).json()["alerts"]
    assert [a["name"] for a in first] == ["Daily summary", "New intents summary"]
    assert [a["id"] for a in first] == [a["id"] for a in again]
    assert first[0]["channels"] == [{"type": "slack", "configured": True}]
    assert client.post(f"{base}/alerts/slack", json={"webhook_url": "https://evil.example.com"}).status_code == 422
    # Summaries over a plain webhook so the content can be checked.
    client.post(f"{base}/intents", json={"name": "Get a refund", "description": "Wants money back."})
    capture(client, p, "s-1", "t1", "I want a refund", "Done.")
    capture(client, p, "s-2", "t2", "I can't log in", "Try again.", success=False)
    client.post(f"{base}/classify", json={})
    for name, metric in (("Daily", None), ("Intents", "suggested_intents")):
        client.post(f"{base}/alerts", json={"name": name, "kind": "summary", "metric": metric,
                                           "channels": [{"type": "webhook", "target": url}]})
    for rule in client.get(f"{base}/alerts").json():
        if rule["channels"][0]["type"] == "slack":
            client.patch(f'/api/alerts/{rule["id"]}', json={"enabled": False})
    fired = client.post(f"{base}/alerts/evaluate").json()["results"]
    assert all(r["fired"] for r in fired) and len(fired) == 2
    deliver(settings)
    texts = sorted(item["text"] for item in received)
    daily = next(t for t in texts if t.startswith("Daily summary for Platform"))
    assert "2 conversations from 2 users, 2 operations, 50.0% succeeded." in daily
    assert "Top intents:\n- Get a refund: 1" in daily
    new_intents = next(t for t in texts if t.startswith("New intents for Platform"))
    assert "- Reset a password (1 conversations): The user cannot sign in." in new_intents


def test_test_send_reports_each_channel(client, webhook):
    url, received = webhook
    p = project(client)
    capture(client, p, "s-1", "t1", "This is frustrating, it does not work", "Sorry")
    rule = client.post(f'/api/projects/{p["id"]}/alerts', json={
        "name": "Frustration", "kind": "threshold", "signal_kind": "frustration", "threshold": 100,
        "channels": [{"type": "webhook", "target": url}, {"type": "email", "target": "ops@example.com"}]}).json()
    result = client.post(f'/api/alerts/{rule["id"]}/test').json()
    assert result["title"] == "Test: Frustration" and "1 flagged conversations" in result["body"]
    assert result["results"] == [{"type": "webhook", "ok": True, "error": None},
                                 {"type": "email", "ok": False, "error": "email_not_configured"}]
    assert received[0]["text"].startswith("[Test] Test: Frustration")
    assert client.get(f'/api/alerts/{rule["id"]}/history').json() == []


# ---- plans ----

def owner_project(client, signup_headers=None):
    owner = client.post("/api/auth/signup", json={"email": "owner@example.com", "password": "password-123"},
                        headers=signup_headers).json()
    headers = {"Authorization": f'Bearer {owner["session"]}'}
    org = owner["organization"]["id"]
    created = client.post(f"/api/orgs/{org}/projects", json={"name": "Shop"}, headers=headers).json()
    return org, created, headers


def test_plan_tiers_rolling_usage_and_quota(client):
    tiers = {t["name"]: t for t in client.get("/api/plans").json()}
    assert tiers["free"]["monthly_event_limit"] == 1000 and tiers["free"]["retention_days"] == 7
    assert tiers["pro"]["monthly_event_limit"] == 1_000_000 and tiers["starter"]["usage_window_days"] == 30
    org, created, headers = owner_project(client)
    p = {"id": created["id"]}
    changed = client.put(f"/api/orgs/{org}/plan", json={"name": "free", "monthly_event_limit": 2}, headers=headers).json()
    assert changed == {"org_id": org, "plan": "free", "monthly_event_limit": 2, "retention_days": 7}
    capture(client, p, "s-1", "t1", "Hello", "Hi")  # a turn pair is one event
    billing = client.get(f"/api/orgs/{org}/billing", headers=headers).json()
    assert billing["used_this_month"] == 1 and billing["retention_days"] == 7 and billing["usage_window_days"] == 30
    capture(client, p, "s-1", "c1", result="ok", parent_id="t1", name="lookup")
    over = client.post("/api/v1/capture-event", headers={"x-org-id": p["id"]}, json={
        "event_id": "t2", "session_id": "s-1", "primitive_name": "agent", "args": "Again", "result": "Hi"})
    assert over.status_code == 429


def test_plan_retention_caps_project_retention(client):
    org, created, headers = owner_project(client)
    client.put(f"/api/orgs/{org}/plan", json={"name": "free"}, headers=headers)
    p = {"id": created["id"]}
    capture(client, p, "old", "t-old", "Old question", "Old answer", minutes_ago=10 * 24 * 60)
    capture(client, p, "new", "t-new", "New question", "New answer")
    events = client.get(f'/api/projects/{p["id"]}/events', params={"range": "all"}, headers=headers).json()
    assert {e["session_id"] for e in events["events"]} == {"new"}


def test_only_the_operator_changes_plans_when_an_admin_token_is_set(settings):
    with TestClient(create_app(replace(settings, admin_token="admin-secret", demo_enabled=False))) as client:
        org, _, headers = owner_project(client, {"Authorization": "Bearer admin-secret"})
        assert client.put(f"/api/orgs/{org}/plan", json={"name": "pro"}, headers=headers).status_code == 403
        operator = client.put(f"/api/orgs/{org}/plan", json={"name": "pro"},
                              headers={"Authorization": "Bearer admin-secret"})
        assert operator.status_code == 200 and operator.json()["monthly_event_limit"] == 1_000_000


# ---- MCP ----

def rpc(client, method, params=None, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                       headers=headers).json()


def test_mcp_exposes_analytics_tools(client):
    org, created, headers = owner_project(client)
    token = headers["Authorization"].split(" ", 1)[1]
    p = {"id": created["id"]}
    capture(client, p, "s-1", "t1", "Where is my parcel?", "Checking", latency=400)
    capture(client, p, "s-1", "c1", result="Error: upstream 503", parent_id="t1", name="shipping.track", success=False)
    names = {tool["name"] for tool in rpc(client, "tools/list", token=token)["result"]["tools"]}
    assert {"tervik_summary", "tervik_tool_stats", "tervik_list_errors", "tervik_intent_stats",
            "tervik_list_violations", "tervik_search"} <= names

    def call(name, **arguments):
        reply = rpc(client, "tools/call", {"name": name, "arguments": {"project_id": p["id"], **arguments}}, token)
        return json.loads(reply["result"]["content"][0]["text"]) if "result" in reply else reply["error"]

    assert call("tervik_summary")["total_calls"] == 2
    assert call("tervik_tool_stats")["tools"][0]["name"] == "shipping.track"
    errors = call("tervik_list_errors")
    assert errors["total"] == 1 and errors["top_messages"][0]["message"] == "Error: upstream 503"
    assert call("tervik_search", query="parcel")["total"] == 1
    assert call("tervik_search", query="x")["code"] == -32602
    assert call("tervik_summary", range="2w")["code"] == -32602
    assert "intents" in call("tervik_intent_stats") and "policies" in call("tervik_list_violations")
    stranger = client.post("/api/auth/signup", json={"email": "s@example.com", "password": "password-123"}).json()
    denied = rpc(client, "tools/call", {"name": "tervik_summary", "arguments": {"project_id": p["id"]}}, stranger["session"])
    assert denied["error"]["code"] == -32004
