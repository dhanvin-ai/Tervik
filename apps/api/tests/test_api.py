from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import sys
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.config import Settings
from app.db import Event
from app.main import create_app
from app.mirror import mirror_events


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path / 'events.db'}")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def project(client, name="Test Agent", headers=None):
    response = client.post("/api/projects", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def event(id="event-1", conversation_id="conversation-1", **values):
    return {"id": id, "conversation_id": conversation_id, "user_id": "user-1", "role": "user", "content": "Find my invoice", **values}


def ingest(client, p, events):
    return client.post("/v1/events", json={"events": events}, headers={"Authorization": f'Bearer {p["api_key"]}'})


def overview(client, p, range="7d"):
    response = client.get("/api/overview", params={"project_id": p["id"], "range": range})
    assert response.status_code == 200, response.text
    return response.json()


def test_project_secrets_and_ingest_auth(client):
    p = project(client)
    assert "api_key" not in client.get("/api/projects").json()[0]
    assert client.get(f'/api/projects/{p["id"]}/key').json() == {"api_key": p["api_key"]}
    assert client.post("/v1/events", json={"events": [event()]}).status_code == 401
    assert ingest(client, {"api_key": "bad"}, [event()]).status_code == 401
    assert ingest(client, p, [event()]).json() == {"accepted": 1, "duplicates": 0}


def test_admin_guards_every_dashboard_endpoint(settings):
    admin = {"Authorization": "Bearer admin-secret"}
    with TestClient(create_app(replace(settings, admin_token="admin-secret", demo_enabled=False))) as client:
        p = project(client, headers=admin)
        paths = ["/api/projects", f'/api/projects/{p["id"]}/key', "/api/overview", "/api/clusters", "/api/clusters/missing", "/api/conversations", "/api/conversations/missing"]
        for path in paths:
            assert client.get(path).status_code == 401
            assert client.get(path, headers={"Authorization": f'Bearer {p["api_key"]}'}).status_code == 401
        assert client.post("/api/projects", json={"name": "No"}).status_code == 401
        assert client.patch("/api/clusters/missing", json={"status": "resolved"}).status_code == 401
        assert client.post("/api/demo/seed").status_code == 401
        assert client.post("/api/demo/seed", headers=admin).status_code == 404
        assert client.get("/api/health").status_code == 200
        assert ingest(client, p, [event()]).status_code == 200
        assert ingest(client, {"api_key": "admin-secret"}, [event()]).status_code == 401


def test_environment_disables_demo_by_default_with_admin(monkeypatch):
    monkeypatch.setenv("TERVIK_ADMIN_TOKEN", "secret")
    monkeypatch.delenv("TERVIK_DEMO_ENABLED", raising=False)
    assert Settings.from_env().demo_enabled is False


def test_cross_project_ids_and_queries_are_isolated(client):
    first, second = project(client, "First"), project(client, "Second")
    assert ingest(client, first, [event(content="That's wrong. I meant an invoice.")]).json()["accepted"] == 1
    assert ingest(client, second, [event(content="Hello there")]).json()["accepted"] == 1
    assert overview(client, first)["metrics"]["failure_rate"] == 100
    assert overview(client, second)["metrics"]["failure_rate"] == 0
    a = client.get("/api/conversations", params={"project_id": first["id"]}).json()[0]
    b = client.get("/api/conversations", params={"project_id": second["id"]}).json()[0]
    assert a["id"] != b["id"]
    assert client.get(f'/api/conversations/{a["id"]}').json()["project_id"] == first["id"]
    assert client.get("/api/clusters", params={"project_id": second["id"]}).json() == []
    assert ingest(client, first, [event(id="foreign", project_id=second["id"])]).status_code == 422
    assert overview(client, second)["metrics"]["messages"] == 1


def test_duplicates_in_batch_and_retries_keep_first_payload(client):
    p = project(client)
    response = ingest(client, p, [event(), event(), event(id="event-2", content="Thank you")])
    assert response.json() == {"accepted": 2, "duplicates": 1}
    assert ingest(client, p, [event(content="That's wrong")]).json() == {"accepted": 0, "duplicates": 1}
    assert overview(client, p)["metrics"]["messages"] == 2
    assert overview(client, p)["metrics"]["failure_rate"] == 0


def test_concurrent_duplicate_batches_are_database_safe(client):
    p = project(client)
    batch = [event(id=f"event-{index}", conversation_id=f"c-{index}") for index in range(12)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: ingest(client, p, batch), range(4)))
    assert all(response.status_code == 200 for response in responses)
    assert sum(response.json()["accepted"] for response in responses) == 12
    assert sum(response.json()["duplicates"] for response in responses) == 36
    assert overview(client, p)["metrics"]["messages"] == 12


@pytest.mark.parametrize("invalid", [
    {"role": "admin"}, {"latency_ms": -1}, {"cost_usd": -1}, {"tokens": -1},
    {"content": "a" * 32_001}, {"timestamp": "2026-01-01T10:00:00"}, {"id": " "},
    {"project_id": "someone-else"}, {"timestamp": "not a time"}, {"tokens": True},
])
def test_invalid_batches_reject_atomically(client, invalid):
    p = project(client)
    response = ingest(client, p, [event(), event(**{"id": "invalid", **invalid})])
    assert response.status_code == 422
    assert overview(client, p)["metrics"]["messages"] == 0


def test_batch_limit_and_empty_rejected(client):
    p = project(client)
    assert ingest(client, p, []).status_code == 422
    assert ingest(client, p, [event(id=f"e-{i}") for i in range(101)]).status_code == 422
    assert overview(client, p)["metrics"]["messages"] == 0


@pytest.mark.parametrize("bad_field", ['"latency_ms":NaN', '"metadata":{"score":Infinity}'])
def test_non_finite_raw_json_is_rejected_without_echoing_payload(client, bad_field):
    p = project(client)
    payload = '{"events":[{"conversation_id":"c","role":"user","content":"private-conversation",' + bad_field + '}]}'
    response = client.post("/v1/events", content=payload,
                           headers={"Authorization": f'Bearer {p["api_key"]}', "Content-Type": "application/json"})
    assert response.status_code == 422
    assert "private-conversation" not in response.text
    assert overview(client, p)["metrics"]["messages"] == 0


def test_body_size_limit(settings):
    with TestClient(create_app(replace(settings, max_body_bytes=1024))) as client:
        p = project(client)
        assert ingest(client, p, [event(content="a" * 1100)]).status_code == 413
        assert overview(client, p)["metrics"]["messages"] == 0


def test_timestamp_normalization_rolling_ranges_and_future_rejection(client, monkeypatch):
    import app.main as main
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(main, "utc_now", lambda: now)
    p = project(client)
    records = [
        event(id="boundary", conversation_id="c-1", timestamp=(now - timedelta(days=7)).isoformat()),
        event(id="outside", conversation_id="c-2", timestamp=(now - timedelta(days=7, seconds=1)).isoformat()),
        event(id="offset", conversation_id="c-3", timestamp=(now - timedelta(hours=2)).astimezone(timezone(timedelta(hours=5, minutes=30))).isoformat()),
    ]
    assert ingest(client, p, records).json()["accepted"] == 3
    assert overview(client, p, "7d")["metrics"]["messages"] == 2
    assert overview(client, p, "24h")["metrics"]["messages"] == 1
    assert overview(client, p, "30d")["metrics"]["messages"] == 3
    summaries = client.get("/api/conversations", params={"project_id": p["id"]}).json()
    detail = client.get(f'/api/conversations/{summaries[0]["id"]}').json()
    assert detail["messages"][0]["timestamp"].endswith("Z")
    assert ingest(client, p, [event(id="future", timestamp=(now + timedelta(minutes=6)).isoformat())]).status_code == 422
    assert client.get("/api/overview", params={"project_id": p["id"], "range": "90d"}).status_code == 422


def test_metrics_evidence_resolution_and_spans(client):
    p = project(client)
    now = datetime.now(timezone.utc)
    messages = [
        event(id="a", content="Find the invoice", timestamp=(now - timedelta(seconds=5)).isoformat()),
        event(id="b", role="assistant", content="Here is the invoice", latency_ms=100, cost_usd=0.002, model="test-model", span_id="parent", metadata={"input": {"query": "invoice"}, "output": "found"}),
        event(id="c", content="That's wrong. I meant yesterday's invoice.", timestamp=now.isoformat()),
        event(id="d", conversation_id="healthy", content="Hello"),
        event(id="e", conversation_id="tool-c", role="tool", content="HTTP 503", status="error", name="billing.lookup", latency_ms=300, cost_usd=0.001, span_id="child", parent_span_id="parent"),
    ]
    assert ingest(client, p, messages).json()["accepted"] == 5
    result = overview(client, p)
    assert result["metrics"] == {"conversations": 3, "messages": 5, "failure_rate": 66.67, "affected_users": 1, "avg_latency_ms": 200, "cost_usd": 0.003}
    cluster = next(row for row in result["top_clusters"] if row["kind"] == "correction")
    detail = client.get(f'/api/clusters/{cluster["id"]}').json()
    assert detail["count"] == 1
    assert detail["evidence"][0]["event_id"] == "c"
    assert "phrase" in detail["evidence"][0]["reason"]
    conv = client.get(f'/api/conversations/{detail["conversations"][0]["id"]}').json()
    assert len(conv["messages"]) == 3 and len(conv["signals"]) == 1
    assert conv["spans"][0]["input"] == {"query": "invoice"}
    assert conv["model"] == "test-model"
    assert client.patch(f'/api/clusters/{cluster["id"]}', json={"status": "resolved"}).json()["status"] == "resolved"
    assert client.get(f'/api/clusters/{cluster["id"]}').json()["status"] == "resolved"
    assert overview(client, p)["metrics"]["failure_rate"] == 66.67
    assert client.get("/api/clusters", params={"project_id": p["id"], "status": "resolved"}).json()[0]["id"] == cluster["id"]
    assert client.get("/api/conversations", params={"project_id": p["id"], "flagged": "false"}).json()[0]["status"] == "healthy"
    assert len(client.get("/api/conversations", params={"project_id": p["id"], "search": "503"}).json()) == 1


def test_repetition_cross_window_and_no_abandonment(client):
    p = project(client)
    now = datetime.now(timezone.utc)
    records = [event(id="old", content="Find my invoice!", timestamp=(now - timedelta(days=8)).isoformat()),
               event(id="new", content="find MY invoice", timestamp=(now - timedelta(hours=1)).isoformat()),
               event(id="ending-user", conversation_id="ending", content="Can you help me?")]
    ingest(client, p, records)
    rows = client.get("/api/clusters", params={"project_id": p["id"]}).json()
    assert [row["kind"] for row in rows] == ["repetition"]
    assert overview(client, p)["metrics"]["failure_rate"] == 50


def test_tool_errors_inherit_recorded_conversation_user_counts(client):
    p = project(client)
    ingest(client, p, [event(id="user"), event(id="tool", role="tool", status="error", content="503", user_id=None)])
    assert overview(client, p)["metrics"]["affected_users"] == 1
    assert client.get("/api/clusters").json()[0]["affected_users"] == 1


def test_cluster_count_distinct_conversations_and_evidence_range(client):
    p = project(client)
    now = datetime.now(timezone.utc)
    ingest(client, p, [event(id="old", conversation_id="old", content="This is frustrating", timestamp=(now - timedelta(days=2)).isoformat()),
                      event(id="new", content="This is frustrating", timestamp=(now - timedelta(hours=1)).isoformat()),
                      event(id="new-2", content="Useless", timestamp=(now - timedelta(minutes=30)).isoformat())])
    row = client.get("/api/clusters", params={"project_id": p["id"]}).json()[0]
    assert row["count"] == 2
    detail = client.get(f'/api/clusters/{row["id"]}', params={"range": "24h"}).json()
    assert detail["count"] == 1 and len(detail["evidence"]) == 2
    assert all(e["conversation_id"] != "old" for e in detail["evidence"])


def test_demo_seed_idempotence_and_sample_labels(client):
    first = client.post("/api/demo/seed").json()
    second = client.post("/api/demo/seed").json()
    assert first["seeded"] is True and second == {"seeded": False, "project_id": first["project_id"]}
    p = client.get("/api/projects").json()[0]
    assert p["is_demo"] is True and p["name"] == "Sample workspace"
    summary = overview(client, p)
    assert summary["metrics"]["conversations"] == 54
    assert {row["kind"] for row in client.get("/api/clusters").json()} == {"correction", "frustration", "repetition", "tool_error"}
    detail = client.get(f'/api/conversations/{summary["recent_conversations"][0]["id"]}').json()
    assert all(message["metadata"]["sample"] for message in detail["messages"])


def test_durable_events_and_resolved_state(settings):
    with TestClient(create_app(settings)) as first:
        p = project(first)
        ingest(first, p, [event(content="That's wrong")])
        id = first.get("/api/clusters").json()[0]["id"]
        first.patch(f"/api/clusters/{id}", json={"status": "resolved"})
    with TestClient(create_app(settings)) as second:
        assert overview(second, p)["metrics"]["messages"] == 1
        assert second.get(f"/api/clusters/{id}").json()["status"] == "resolved"


def test_unknown_ids_and_invalid_status(client):
    assert client.get("/api/overview", params={"project_id": "unknown"}).status_code == 404
    assert client.get("/api/conversations/missing").status_code == 404
    assert client.get("/api/clusters/missing").status_code == 404
    assert client.patch("/api/clusters/missing", json={"status": "invalid"}).status_code == 422
    assert client.get("/api/clusters", params={"status": "invalid"}).status_code == 422


def test_cors_preflight_with_admin(settings):
    with TestClient(create_app(replace(settings, admin_token="secret"))) as client:
        response = client.options("/api/projects", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_clickhouse_mirror_success_and_safe_failure(settings, monkeypatch, caplog):
    module, ch = MagicMock(), MagicMock()
    module.get_client.return_value = ch
    monkeypatch.setitem(sys.modules, "clickhouse_connect", module)
    config = replace(settings, clickhouse_url="http://localhost:8123", clickhouse_password="private-secret")
    records = [{"project_id": "p", "id": "e", "conversation_id": "c", "datetime": datetime.now(timezone.utc), "role": "user", "payload": {"content": "sensitive payload"}}]
    mirror_events(config, records)
    ch.insert.assert_called_once()
    assert ch.insert.call_args.args[0] == "tervik.events"
    ch.close.assert_called_once()
    module.get_client.side_effect = RuntimeError("private-secret sensitive payload")
    mirror_events(config, records)
    assert "mirror failed" in caplog.text
    assert "private-secret" not in caplog.text and "sensitive payload" not in caplog.text
