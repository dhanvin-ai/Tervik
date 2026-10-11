"""Dashboard chat: turns are recorded like real traffic and checked at once."""
import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.playground import ModelUnavailable, calculate

MODELS = [{"id": "ollama:llama3.2:latest", "provider": "ollama", "name": "llama3.2:latest", "label": "llama3.2 · local"}]


def openai_reply(content="", tool_calls=None, tokens=12):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = [{"id": f"call-{i}", "type": "function",
                                  "function": {"name": name, "arguments": json.dumps(args)}}
                                 for i, (name, args) in enumerate(tool_calls)]
    return {"choices": [{"message": message}], "usage": {"total_tokens": tokens}}


class FakeModel:
    """Scripted OpenAI-compatible model: calls a tool when tools are offered for
    math or the shop, then answers from the tool result."""

    def __init__(self):
        self.requests = []

    def __call__(self, url, body, headers):
        self.requests.append(body)
        last = body["messages"][-1]
        if last["role"] == "tool":
            return openai_reply(f"Done: {last['content']}")
        text = last["content"].lower()
        if body.get("tools") and "%" in text:
            return openai_reply(tool_calls=[("calculator", {"expression": "18% * 2450"})])
        if body.get("tools") and "hello" in text:
            return openai_reply(tool_calls=[("cancel_subscription", {"email": "[customer email]"})])
        if body.get("tools") and "refund" in text:
            return openai_reply(tool_calls=[("refund_order", {"order_id": "1002", "reason": "unwanted"})])
        return openai_reply("Happy to help!")


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(database_url=f"sqlite:///{tmp_path / 'chat.db'}"))) as client:
        client.app.state.playground_models = lambda: (list(MODELS), None)
        client.app.state.playground_transport = FakeModel()
        yield client


def project(client):
    return client.post("/api/projects", json={"name": "Chat"}).json()


def chat(client, p, message, **values):
    response = client.post(f'/api/projects/{p["id"]}/playground/chat', json={"message": message, **values})
    assert response.status_code == 200, response.text
    return response.json()


def test_status_lists_models_and_personas(client):
    status = client.get("/api/playground/status").json()
    assert status["default_model"] == "ollama:llama3.2:latest" and status["note"] is None
    assert [p["id"] for p in status["personas"]] == ["general", "shop"]
    assert all(p["ideas"] for p in status["personas"])


def test_a_turn_with_a_tool_is_recorded_and_checked(client):
    p = project(client)
    first = chat(client, p, "What is 18% of 2,450?")
    assert first["reply"] == 'Done: {"expression": "18% * 2450", "result": 441.0}'
    assert first["session_id"].startswith("chat-") and first["model"] == "ollama:llama3.2:latest"
    detail = client.get(f'/api/conversations/{first["conversation_id"]}').json()
    roles = [(m["role"], m["name"]) for m in detail["messages"]]
    assert roles == [("user", None), ("tool", "calculator"), ("assistant", "chat-assistant")]
    tool = detail["messages"][1]
    assert tool["status"] == "success" and tool["trace_id"] == detail["messages"][2]["trace_id"]
    assert detail["status"] == "healthy"
    # The follow-up carries the conversation so far, and its problems appear at once.
    second = chat(client, p, "That is wrong, this is frustrating", session_id=first["session_id"])
    sent = client.app.state.playground_transport.requests[-1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert "tools" not in client.app.state.playground_transport.requests[-1]
    detail = client.get(f'/api/conversations/{second["conversation_id"]}').json()
    assert set(detail["tags"]) == {"correction", "frustration"}
    chats = client.get(f'/api/projects/{p["id"]}/playground/chats').json()
    assert chats == [{**chats[0], "session_id": first["session_id"], "title": "What is 18% of 2,450?",
                      "persona": "general", "problems": ["correction", "frustration"]}]


def test_shop_agent_failures_are_flagged(client):
    p = project(client)
    hello = chat(client, p, "hello", persona="shop")
    tags = set(client.get(f'/api/conversations/{hello["conversation_id"]}').json()["tags"])
    assert tags == {"tool_bad_input", "unrequested_action"}
    refund = chat(client, p, "Refund order 1002", persona="shop")
    detail = client.get(f'/api/conversations/{refund["conversation_id"]}').json()
    assert "tool_error" in detail["tags"]
    assert any(m["role"] == "tool" and m["status"] == "error" for m in detail["messages"])
    clusters = {c["kind"] for c in client.get("/api/clusters", params={"project_id": p["id"]}).json()}
    assert {"tool_bad_input", "unrequested_action", "tool_error"} <= clusters


def test_model_problems_are_reported_not_recorded(client):
    p = project(client)

    def down(url, body, headers):
        raise ModelUnavailable("cannot reach the model (Connection refused)")

    client.app.state.playground_transport = down
    failed = client.post(f'/api/projects/{p["id"]}/playground/chat', json={"message": "hi"})
    assert failed.status_code == 424 and "brew services start ollama" in failed.json()["detail"]
    assert client.post(f'/api/projects/{p["id"]}/playground/chat',
                       json={"message": "hi", "model": "ollama:missing"}).status_code == 424
    client.app.state.playground_models = lambda: ([], "Ollama is not running. Start it with: brew services start ollama")
    none = client.post(f'/api/projects/{p["id"]}/playground/chat', json={"message": "hi"})
    assert none.status_code == 424 and none.json()["detail"].startswith("Ollama is not running")
    assert client.get(f'/api/projects/{p["id"]}/playground/chats').json() == []
    assert client.post(f'/api/projects/{p["id"]}/playground/chat', json={"message": ""}).status_code == 422
    assert client.post(f'/api/projects/{p["id"]}/playground/chat', json={"message": "hi", "persona": "x"}).status_code == 422


def test_api_keys_and_strangers_cannot_chat(client):
    p = project(client)
    secret = client.post(f'/api/projects/{p["id"]}/api-keys', json={"name": "ci"}).json()["secret"]
    assert client.post(f'/api/projects/{p["id"]}/playground/chat', json={"message": "hi"},
                       headers={"x-api-key": secret}).status_code == 403
    owner = client.post("/api/auth/signup", json={"email": "o@example.com", "password": "password-123"}).json()
    other = client.post("/api/auth/signup", json={"email": "x@example.com", "password": "password-123"}).json()
    created = client.post(f'/api/orgs/{owner["organization"]["id"]}/projects', json={"name": "Shop"},
                          headers={"Authorization": f'Bearer {owner["session"]}'}).json()
    url = f'/api/projects/{created["id"]}/playground/chat'
    assert client.post(url, json={"message": "hi"}, headers={"Authorization": f'Bearer {other["session"]}'}).status_code == 404
    assert client.post(url, json={"message": "hi"}, headers={"Authorization": f'Bearer {owner["session"]}'}).status_code == 200


def test_calculator_reads_percentages():
    assert calculate("18% * 2450")["result"] == 441.0
    assert calculate("10 % 3")["result"] == 1
    assert calculate("2,450 * 0.18")["result"] == 441.0
