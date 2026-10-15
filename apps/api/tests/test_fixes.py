"""Fixing a problem group: a suggested fix, a replay with it, then approval."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import fixes
from app.config import Settings
from app.db import utc_now
from app.main import create_app


class FakeLLM:
    """Plays every role in the fix flow, recording which it was asked for."""
    model = "fake-model"

    def __init__(self, healthy_turns_get_worse=False):
        self.calls, self.worse = [], healthy_turns_get_worse

    def tool_call(self, *, system, prompt, tool, max_tokens=2048):
        self.calls.append(tool["name"])
        if tool["name"] == "propose_fix":
            assert "refund" in prompt.lower()  # it reads the real conversations
            return {"title": "Confirm the refund ran before saying it's done",
                    "cause": "The agent says a refund is issued without calling a refund tool.",
                    "instructions": ["Call refund_payment before telling the user a refund is issued.",
                                     "If you can't, tell the user what happens next instead."],
                    "confidence": "high", "caveat": "Refund tool calls might not be recorded."}
        if tool["name"] == "agent_turn":
            assert "refund_payment before" in system  # the replay runs with the fix
            return {"tool_calls": [], "reply": "I can't issue that refund myself, so I've passed it to our team."}
        if tool["name"] == "judge_turn":
            return {"verdict": "fixed", "reason": "The new reply no longer claims the refund was issued."}
        if tool["name"] == "compare_turns":
            return {"verdict": "worse" if self.worse else "same_or_better", "reason": "Same answer as before."}
        raise AssertionError(tool["name"])


def turn(client, project_id, session_id, user, reply, minutes_ago=30):
    client.post("/api/v1/capture-session", json={"session_id": session_id, "user_data": {"user_id": f"user-{session_id}"}},
                headers={"x-org-id": project_id})
    stamp = int((utc_now() - timedelta(minutes=minutes_ago)).timestamp() * 1000)
    response = client.post("/api/v1/capture-event", headers={"x-org-id": project_id}, json={
        "event_id": f"{session_id}-1", "session_id": session_id, "primitive_name": "shop-agent",
        "args": user, "result": reply, "timestamp": stamp, "latency": 400})
    assert response.status_code == 200, response.text


@pytest.fixture
def shop(tmp_path):
    with TestClient(create_app(Settings(database_url=f"sqlite:///{tmp_path / 'fixes.db'}"))) as client:
        project = client.post("/api/projects", json={"name": "Shop"}).json()
        for n in range(3):
            turn(client, project["id"], f"refund-{n}", "I want a refund for my order", "Done. I've refunded your order.", 40 + n)
        for n in range(2):
            turn(client, project["id"], f"hours-{n}", "When are you open?", "We're open 9 to 5, Monday to Friday.", 20 + n)
        problems = client.get(f"/api/clusters?project_id={project['id']}&range=7d").json()
        problem = next(p for p in problems if p["kind"] == "unsupported_claim")
        yield SimpleNamespace(client=client, project=project, problem=problem)


def test_suggest_replay_and_approve_a_fix(shop):
    client, problem = shop.client, shop.problem
    client.app.state.llm = llm = FakeLLM()
    assert client.get(f"/api/clusters/{problem['id']}/fix").json() == {"fix": None, "can_replay": True}

    fix = client.post(f"/api/clusters/{problem['id']}/fix").json()
    assert fix["fix"]["source"] == "claude" and fix["state"] == "candidate_ready"
    assert "+ Call refund_payment before telling the user a refund is issued." in fix["candidate_diff"]
    assert client.get(f"/api/clusters/{problem['id']}/fix").json()["fix"]["id"] == fix["id"]
    # Nothing is approved before it has been replayed.
    assert client.post(f"/api/improvements/{fix['id']}/approve").status_code == 422

    replayed = client.post(f"/api/improvements/{fix['id']}/replay").json()
    summary = replayed["replay"]["summary"]
    assert (summary["failing"], summary["fixed"], summary["controls"], summary["worse"]) == (3, 3, 2, 0)
    assert replayed["state"] == "awaiting_approval"
    assert all(row["replayed"].endswith("passed it to our team.") for row in replayed["replay"]["results"])
    assert llm.calls.count("agent_turn") == 5 and llm.calls.count("judge_turn") == 3

    approved = client.post(f"/api/improvements/{fix['id']}/approve").json()
    assert approved["state"] == "monitoring" and approved["deployed_at"]
    assert "measurement" in approved
    assert "Call refund_payment before telling the user" in approved["coding_agent_prompt"]
    assert client.get(f"/api/clusters/{problem['id']}?range=7d").json()["status"] == "resolved"
    prompts = client.get(f"/api/projects/{shop.project['id']}/prompts").json()
    assert [(p["path"], p["status"]) for p in prompts] == [("prompts/system.md", "active")]


def test_a_fix_that_makes_healthy_turns_worse_cannot_be_approved(shop):
    client, problem = shop.client, shop.problem
    client.app.state.llm = FakeLLM(healthy_turns_get_worse=True)
    fix = client.post(f"/api/clusters/{problem['id']}/fix").json()
    replayed = client.post(f"/api/improvements/{fix['id']}/replay").json()
    assert replayed["replay"]["summary"]["worse"] == 2 and replayed["state"] == "candidate_ready"
    assert client.post(f"/api/improvements/{fix['id']}/approve").status_code == 422


def test_without_a_model_the_fix_comes_from_the_template_and_cannot_be_replayed(shop):
    client, problem = shop.client, shop.problem
    client.app.state.llm = None
    assert client.get(f"/api/clusters/{problem['id']}/fix").json()["can_replay"] is False
    fix = client.post(f"/api/clusters/{problem['id']}/fix").json()
    assert fix["fix"]["source"] == "template" and fix["fix"]["instructions"]
    assert client.post(f"/api/improvements/{fix['id']}/replay").status_code == 409


def test_a_user_side_signal_replays_the_agent_turn_before_it():
    def event(id, role, minute, content=""):
        return SimpleNamespace(id=id, role=role, content=content, timestamp=utc_now() + timedelta(minutes=minute),
                               conversation_id="c", name=None, status="success", event_metadata={})
    events = [event("u1", "user", 0, "Book Paris"), event("a1", "assistant", 1, "Booked Rome."),
              event("u2", "user", 2, "No, that's wrong. I said Paris.")]
    case = fixes.failing_turn(events, events[2])
    assert case["user"].id == "u1" and [e.id for e in case["turn"]] == ["a1"] and case["next"].id == "u2"
