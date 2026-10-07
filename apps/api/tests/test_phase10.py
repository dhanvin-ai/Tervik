"""Phase 10 gate: hosted MCP serves authorized coding agents; isolation holds."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path / 'phase10.db'}")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def rpc(client, method, params=None, token=None, rpc_id=1):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": rpc_id, "method": method,
                                    "params": params or {}}, headers=headers).json()


def test_mcp_initialize_and_auth(client):
    hello = rpc(client, "initialize", {"protocolVersion": "2025-06-18"})
    assert hello["result"]["serverInfo"]["name"] == "tervik"
    assert rpc(client, "tools/list")["error"]["code"] == -32001
    assert rpc(client, "nope")["error"]["code"] == -32601
    assert rpc(client, "tools/call", {"name": "x", "arguments": {}})["error"]["code"] == -32001


def test_mcp_tools_end_to_end_with_isolation(client):
    first = client.post("/api/auth/signup",
                        json={"email": "a@example.com", "password": "password-123"}).json()
    second = client.post("/api/auth/signup",
                         json={"email": "b@example.com", "password": "password-123"}).json()
    headers_a = {"Authorization": f'Bearer {first["session"]}'}
    project = client.post(f'/api/orgs/{first["organization"]["id"]}/projects',
                          json={"name": "Shop"}, headers=headers_a).json()
    now = datetime.now(timezone.utc)
    client.post("/v1/events", json={"events": [
        {"id": "e-1", "conversation_id": "c-1", "role": "user", "content": "Find my invoice",
         "timestamp": (now - timedelta(hours=1)).isoformat()}]},
        headers={"Authorization": f'Bearer {project["credential"]["secret"]}'})
    tools = rpc(client, "tools/list", token=first["session"])
    assert {t["name"] for t in tools["result"]["tools"]} >= {
        "tervik_list_conversations", "tervik_get_conversation", "tervik_list_clusters",
        "tervik_get_cluster", "tervik_list_intents", "tervik_get_improvement",
        "tervik_ops_summary"}
    convs = rpc(client, "tools/call", {"name": "tervik_list_conversations",
                                       "arguments": {"project_id": project["id"]}},
                token=first["session"])
    items = __import__("json").loads(convs["result"]["content"][0]["text"])
    assert len(items) == 1
    detail = rpc(client, "tools/call", {"name": "tervik_get_conversation",
                                        "arguments": {"conversation_id": items[0]["id"]}},
                 token=first["session"])
    assert "messages" in detail["result"]["content"][0]["text"]
    ops = rpc(client, "tools/call", {"name": "tervik_ops_summary", "arguments": {}},
              token=first["session"])
    assert "backlog" in ops["result"]["content"][0]["text"]
    # Cross-organization access fails through MCP too.
    other = rpc(client, "tools/call", {"name": "tervik_list_conversations",
                                       "arguments": {"project_id": project["id"]}},
                 token=second["session"])
    assert other["error"]["code"] == -32004
    assert rpc(client, "tools/call", {"name": "tervik_get_conversation",
                                      "arguments": {"conversation_id": items[0]["id"]}},
               token=second["session"])["error"]["code"] == -32004
    assert rpc(client, "tools/call", {"name": "tervik_nope", "arguments": {}},
               token=first["session"])["error"]["code"] == -32602
    audit = client.get(f'/api/orgs/{first["organization"]["id"]}/audit', headers=headers_a).json()
    assert any(e["action"] == "mcp.call" for e in audit)
