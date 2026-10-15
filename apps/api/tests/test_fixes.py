"""Fixing a problem group: the coding agent in the customer's project downloads the
failing turns, fixes the agent, replays them, and reports; a person approves."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import fixes
from app.config import Settings
from app.db import utc_now
from app.main import create_app


class NoModel:
    """Tervik itself never calls a model to fix a problem."""
    def tool_call(self, **_):
        raise AssertionError("The fix flow must not call a model")


def turn(client, project_id, session_id, user, reply, minutes_ago=30):
    client.post("/api/v1/capture-session", json={"session_id": session_id, "user_data": {"user_id": f"user-{session_id}"}},
                headers={"x-org-id": project_id})
    stamp = int((utc_now() - timedelta(minutes=minutes_ago)).timestamp() * 1000)
    response = client.post("/api/v1/capture-event", headers={"x-org-id": project_id}, json={
        "event_id": f"{session_id}-1", "session_id": session_id, "primitive_name": "shop-agent",
        "args": user, "result": reply, "timestamp": stamp, "latency": 400})
    assert response.status_code == 200, response.text


def report(cases, fixed=True, worse=False):
    """What the fix agent sends after replaying every case through the real agent."""
    rows = [{"conversation_id": case["conversation_id"], "group": "failing", "verdict": "fixed" if fixed else "still_failing",
             "reason": "It no longer claims the refund was issued.", "user": case["user"],
             "original": case["turn"][-1]["content"], "replayed": "I can't issue that refund myself, so I've passed it to our team."}
            for case in cases["failing"]]
    rows += [{"conversation_id": case["conversation_id"], "group": "control", "verdict": "worse" if worse else "same_or_better",
              "reason": "Same answer as before.", "user": case["user"], "original": case["turn"][-1]["content"],
              "replayed": case["turn"][-1]["content"]} for case in cases["controls"]]
    return {"title": "Confirm the refund ran before saying it's done",
            "cause": "The agent says a refund is issued without calling a refund tool.",
            "diff": "--- a/agent/prompt.py\n+++ b/agent/prompt.py\n+Call refund_payment before telling the user a refund is issued.\n",
            "files": ["agent/prompt.py"], "agent": "Claude Code", "results": rows}


@pytest.fixture
def shop(tmp_path):
    with TestClient(create_app(Settings(database_url=f"sqlite:///{tmp_path / 'fixes.db'}"))) as client:
        client.app.state.llm = NoModel()
        project = client.post("/api/projects", json={"name": "Shop"}).json()
        for n in range(3):
            turn(client, project["id"], f"refund-{n}", "I want a refund for my order", "Done. I've refunded your order.", 40 + n)
        for n in range(2):
            turn(client, project["id"], f"hours-{n}", "When are you open?", "We're open 9 to 5, Monday to Friday.", 20 + n)
        problems = client.get(f"/api/clusters?project_id={project['id']}&range=7d").json()
        problem = next(p for p in problems if p["kind"] == "unsupported_claim")
        key = client.post(f"/api/projects/{project['id']}/api-keys", json={"name": "fix agent"}).json()["secret"]
        yield SimpleNamespace(client=client, project=project, problem=problem, agent={"X-API-Key": key})


def test_the_coding_agent_fixes_a_problem_and_a_person_approves_it(shop):
    client, problem, agent = shop.client, shop.problem, shop.agent
    waiting = client.get(f"/api/clusters/{problem['id']}/fix").json()
    assert waiting["fix"] is None and problem["id"] in waiting["agent_prompt"]

    # The fix agent downloads the failing turns and healthy ones with the project's key.
    cases = client.get(f"/api/clusters/{problem['id']}/cases", headers=agent).json()
    assert cases["problem"]["kind"] == "unsupported_claim"
    assert len(cases["failing"]) == 3 and len(cases["controls"]) == 2
    assert cases["failing"][0]["user"] == "I want a refund for my order"
    assert cases["failing"][0]["turn"][-1]["content"] == "Done. I've refunded your order."
    assert cases["failing"][0]["reason"]

    # It reports its change and the replay; Tervik counts the results itself.
    reported = client.post(f"/api/clusters/{problem['id']}/fix", headers=agent, json=report(cases))
    assert reported.status_code == 201, reported.text
    fix = reported.json()
    assert fix["state"] == "awaiting_approval" and fix["fix"]["agent"] == "Claude Code"
    summary = fix["replay"]["summary"]
    assert (summary["failing"], summary["fixed"], summary["controls"], summary["worse"]) == (3, 3, 2, 0)
    assert client.get(f"/api/clusters/{problem['id']}/fix").json()["fix"]["id"] == fix["id"]

    # The key can't approve; a person in the dashboard does.
    assert client.post(f"/api/improvements/{fix['id']}/approve", headers=agent).status_code == 403
    approved = client.post(f"/api/improvements/{fix['id']}/approve").json()
    assert approved["state"] == "monitoring" and approved["deployed_at"] and "measurement" in approved
    assert client.get(f"/api/clusters/{problem['id']}?range=7d").json()["status"] == "resolved"


def test_a_fix_that_makes_healthy_turns_worse_cannot_be_approved(shop):
    client, problem, agent = shop.client, shop.problem, shop.agent
    cases = client.get(f"/api/clusters/{problem['id']}/cases", headers=agent).json()
    fix = client.post(f"/api/clusters/{problem['id']}/fix", headers=agent, json=report(cases, worse=True)).json()
    assert fix["replay"]["summary"]["worse"] == 2 and fix["state"] == "candidate_ready"
    assert client.post(f"/api/improvements/{fix['id']}/approve").status_code == 422


def test_a_fix_that_fixed_nothing_cannot_be_approved(shop):
    client, problem, agent = shop.client, shop.problem, shop.agent
    cases = client.get(f"/api/clusters/{problem['id']}/cases", headers=agent).json()
    fix = client.post(f"/api/clusters/{problem['id']}/fix", headers=agent, json=report(cases, fixed=False)).json()
    assert fix["state"] == "candidate_ready"
    assert client.post(f"/api/improvements/{fix['id']}/approve").status_code == 422


def test_a_report_must_say_what_each_replayed_turn_did(shop):
    client, problem, agent = shop.client, shop.problem, shop.agent
    cases = client.get(f"/api/clusters/{problem['id']}/cases", headers=agent).json()
    body = report(cases)
    body["results"][-1]["verdict"] = "fixed"  # a healthy turn can only stay the same or get worse
    assert client.post(f"/api/clusters/{problem['id']}/fix", headers=agent, json=body).status_code == 422


def test_a_key_only_reaches_its_own_projects_problems(shop):
    client, problem = shop.client, shop.problem
    other = client.post("/api/projects", json={"name": "Other"}).json()
    other_key = {"X-API-Key": client.post(f"/api/projects/{other['id']}/api-keys", json={"name": "x"}).json()["secret"]}
    assert client.get(f"/api/clusters/{problem['id']}/cases", headers=other_key).status_code == 404
    cases = client.get(f"/api/clusters/{problem['id']}/cases", headers=shop.agent).json()
    assert client.post(f"/api/clusters/{problem['id']}/fix", headers=other_key, json=report(cases)).status_code == 404


def test_a_user_side_signal_replays_the_agent_turn_before_it():
    def event(id, role, minute, content=""):
        return SimpleNamespace(id=id, role=role, content=content, timestamp=utc_now() + timedelta(minutes=minute),
                               conversation_id="c", name=None, status="success", event_metadata={})
    events = [event("u1", "user", 0, "Book Paris"), event("a1", "assistant", 1, "Booked Rome."),
              event("u2", "user", 2, "No, that's wrong. I said Paris.")]
    case = fixes.failing_turn(events, events[2])
    assert case["user"].id == "u1" and [e.id for e in case["turn"]] == ["a1"] and case["next"].id == "u2"
    view = fixes.case_view(case, "correction", "The user corrected the agent.")
    assert view["user"] == "Book Paris" and view["turn"] == [{"role": "assistant", "content": "Booked Rome."}]
    assert view["next"] == "No, that's wrong. I said Paris."
