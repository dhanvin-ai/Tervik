"""Phase 4 gate: historical import keeps original timestamps and relationships."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path / 'phase4.db'}")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def test_historical_import_preserves_timestamps_and_spans(client):
    project = client.post("/api/projects", json={"name": "History"}).json()
    headers = {"Authorization": f'Bearer {project["api_key"]}'}
    base = datetime.now(timezone.utc) - timedelta(days=30)
    events = [
        {"id": "hist-user", "conversation_id": "old-conv", "user_id": "u-1", "role": "user",
         "content": "Old question", "timestamp": base.isoformat()},
        {"id": "hist-tool", "conversation_id": "old-conv", "user_id": "u-1", "role": "tool",
         "content": "old output", "status": "success", "name": "lookup",
         "trace_id": "hist-trace", "span_id": "hist-child", "parent_span_id": "hist-parent",
         "timestamp": (base + timedelta(seconds=2)).isoformat()},
        {"id": "hist-asst", "conversation_id": "old-conv", "user_id": "u-1", "role": "assistant",
         "content": "Old answer", "trace_id": "hist-trace", "span_id": "hist-parent",
         "timestamp": (base + timedelta(seconds=5)).isoformat()},
    ]
    assert client.post("/v1/events", json={"events": events}, headers=headers).json() == {
        "accepted": 3, "duplicates": 0}
    # Re-importing the same history changes nothing.
    assert client.post("/v1/events", json={"events": events}, headers=headers).json() == {
        "accepted": 0, "duplicates": 3}
    conversations = client.get("/api/conversations", params={"project_id": project["id"], "range": "30d"}).json()
    assert len(conversations) == 1
    detail = client.get(f'/api/conversations/{conversations[0]["id"]}').json()
    assert [m["id"] for m in detail["messages"]] == ["hist-user", "hist-tool", "hist-asst"]
    spans = {s["id"]: s for s in detail["spans"]}
    assert spans["hist-child"]["parent_id"] == "hist-parent"
