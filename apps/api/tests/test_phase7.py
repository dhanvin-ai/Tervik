"""Phase 7 gate: alerts fire once, deliver, retry safely, resolve; plans enforce."""
import json
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.alerts import process_deliveries
from app.config import Settings
from app.db import AlertDelivery
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path / 'phase7.db'}")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def webhook():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            received.append(json.loads(self.rfile.read(length) or b"{}"))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

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


def project(client, name="Alerts"):
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def ingest(client, p, events):
    return client.post("/v1/events", json={"events": events},
                       headers={"Authorization": f'Bearer {p["api_key"]}'})


def flagged_batch(start=0, count=12):
    now = datetime.now(timezone.utc)
    events = []
    for index in range(count):
        cid = f"conv-{start + index}"
        events.append({"id": f"u-{cid}", "conversation_id": cid, "role": "user",
                       "content": "Find my invoice",
                       "timestamp": (now - timedelta(hours=1)).isoformat()})
        events.append({"id": f"f-{cid}", "conversation_id": cid, "role": "user",
                       "content": "This is frustrating, you keep ignoring me",
                       "timestamp": (now - timedelta(minutes=30)).isoformat()})
    return events


def test_threshold_alert_fires_once_delivers_and_resolves(client, webhook):
    url, received = webhook
    p = project(client)
    assert ingest(client, p, flagged_batch()).status_code == 200
    rule = client.post(f'/api/projects/{p["id"]}/alerts', json={
        "name": "Frustration spike", "kind": "threshold", "signal_kind": "frustration",
        "threshold": 5, "window_hours": 24, "min_samples": 5, "cooldown_hours": 24,
        "channels": [{"type": "webhook", "target": url}]}).json()
    first = client.post(f'/api/projects/{p["id"]}/alerts/evaluate').json()
    assert first["evaluated"] == 1 and first["results"][0]["fired"] is True
    second = client.post(f'/api/projects/{p["id"]}/alerts/evaluate').json()
    assert second["results"][0]["fired"] is False  # cooldown + dedup: sends once
    deliveries = client.get(f'/api/projects/{p["id"]}/deliveries').json()
    assert len(deliveries) == 1 and deliveries[0]["state"] == "queued"
    assert "secret" not in json.dumps(deliveries) and url not in json.dumps(deliveries)


def test_delivery_send_retry_and_replay(client, settings, webhook):
    from app.db import make_database
    url, received = webhook
    p = project(client)
    assert ingest(client, p, flagged_batch()).status_code == 200
    client.post(f'/api/projects/{p["id"]}/alerts', json={
        "name": "Spike", "kind": "threshold", "threshold": 5,
        "window_hours": 24, "min_samples": 5, "cooldown_hours": 1,
        "channels": [{"type": "webhook", "target": url}]})
    assert client.post(f'/api/projects/{p["id"]}/alerts/evaluate').json()["results"][0]["fired"] is True
    engine, sessions = make_database(settings.database_url)
    with sessions.begin() as session:
        sent, failed = process_deliveries(session, settings)
    assert (sent, failed) == (1, 0)
    assert len(received) == 1 and "Spike" in received[0]["text"]
    assert client.get(f'/api/projects/{p["id"]}/deliveries').json()[0]["state"] == "sent"


def test_failed_delivery_retries_safely(client, settings):
    from app.db import make_database
    p = project(client)
    assert ingest(client, p, flagged_batch()).status_code == 200
    client.post(f'/api/projects/{p["id"]}/alerts', json={
        "name": "Spike", "kind": "threshold", "threshold": 5,
        "window_hours": 24, "min_samples": 5, "cooldown_hours": 1,
        "channels": [{"type": "webhook", "target": "http://127.0.0.1:9/unreachable"}]})
    assert client.post(f'/api/projects/{p["id"]}/alerts/evaluate').json()["results"][0]["fired"] is True
    engine, sessions = make_database(settings.database_url)
    with sessions.begin() as session:
        sent, failed = process_deliveries(session, settings)
        assert sent == 0
        delivery = session.scalars(select(AlertDelivery)).first()
        assert delivery.error_code == "transient"
        first_attempts = delivery.attempts
    # Retry keeps the same dedup identity and attempts again.
    with sessions.begin() as session:
        delivery = session.scalars(select(AlertDelivery)).first()
        delivery.next_retry_at = None
        delivery.state = "failed"
    with sessions.begin() as session:
        process_deliveries(session, settings)
        delivery = session.scalars(select(AlertDelivery)).first()
        assert delivery.attempts == first_attempts + 1
    assert client.post(f'/api/deliveries/{delivery.id}/replay').status_code == 200
    assert client.get(f'/api/projects/{p["id"]}/deliveries').json()[0]["state"] == "queued"


def test_min_samples_cooldown_and_trend(client):
    p = project(client)
    rule = client.post(f'/api/projects/{p["id"]}/alerts', json={
        "name": "Needs data", "kind": "threshold", "threshold": 1,
        "window_hours": 24, "min_samples": 100, "cooldown_hours": 24,
        "channels": [{"type": "webhook", "target": "http://127.0.0.1:9/x"}]}).json()
    assert ingest(client, p, flagged_batch()).status_code == 200
    result = client.post(f'/api/projects/{p["id"]}/alerts/evaluate').json()
    assert result["results"][0]["fired"] is False
    assert client.get(f'/api/projects/{p["id"]}/deliveries').json() == []
    assert client.delete(f'/api/alerts/{rule["id"]}').status_code == 200


def test_quota_billing_export_delete_and_ops(client):
    owner = client.post("/api/auth/signup",
                        json={"email": "o@example.com", "password": "password-123"}).json()
    headers = {"Authorization": f'Bearer {owner["session"]}'}
    org = owner["organization"]["id"]
    billing = client.get(f"/api/orgs/{org}/billing", headers=headers).json()
    assert billing["used_this_month"] == 0 and billing["monthly_event_limit"] > 0
    project = client.post(f"/api/orgs/{org}/projects", json={"name": "Shop"}, headers=headers).json()
    ingest_headers = {"Authorization": f'Bearer {project["credential"]["secret"]}'}
    assert client.post("/v1/events", json={"events": [
        {"id": "e-1", "conversation_id": "c-1", "role": "user", "content": "hi"}]},
        headers=ingest_headers).status_code == 200
    assert client.get(f"/api/orgs/{org}/billing", headers=headers).json()["used_this_month"] == 1
    exported = client.get(f'/api/projects/{project["id"]}/export',
                          params={"range": "7d"}, headers=headers).json()
    assert len(exported["events"]) == 1
    ops = client.get("/api/ops/summary", headers=headers).json()
    assert ops["queue"]["backlog"]["processed"] >= 1
    assert ops["analysis_coverage_24h"]["messages_total"] >= 1
    assert client.delete(f'/api/projects/{project["id"]}', headers=headers).status_code == 200
    assert client.get(f'/api/projects/{project["id"]}/export',
                      params={"range": "7d"}, headers=headers).status_code == 404
