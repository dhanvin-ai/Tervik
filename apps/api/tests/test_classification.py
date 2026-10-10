"""Intent and policy classification with a scripted LLM (no network)."""
import re
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import classify
from app.config import Settings
from app.db import utc_now
from app.llm import LLMError
from app.main import create_app


class FakeLLM:
    model = "fake-model"

    def __init__(self, respond):
        self.respond, self.calls = respond, []

    def tool_call(self, *, system, prompt, tool, max_tokens=2048):
        self.calls.append({"prompt": prompt, "tool": tool["name"]})
        return self.respond(prompt, tool["name"])


def ref(prompt, pattern):
    """The bracketed reference of the first transcript line matching pattern."""
    for line in prompt.splitlines():
        match = re.match(r"\[(M\d+)\] (.*)", line)
        if match and re.search(pattern, match.group(2), re.I):
            return match.group(1)
    return None


def listed(prompt, prefix, name):
    match = re.search(rf"^({prefix}\d+): {re.escape(name)}", prompt, re.M)
    return match.group(1) if match else None


def reviewer(prompt, tool):
    """Refund requests match the refund intent; leaking an account number
    breaks the policy; anything else gets a suggested intent."""
    if tool != "record_findings":
        return {}
    findings = {"intents": [], "violations": []}
    refund = ref(prompt, r"^User: .*refund")
    if refund and listed(prompt, "I", "Get a refund"):
        findings["intents"].append({"intent": listed(prompt, "I", "Get a refund"), "evidence": [refund], "confidence": 0.9})
    leak = ref(prompt, r"^Agent.*account number is \d+")
    if leak and listed(prompt, "P", "Never reveal account numbers"):
        findings["violations"].append({"policy": listed(prompt, "P", "Never reveal account numbers"),
                                       "evidence": [leak], "reason": "The agent read out the full account number."})
    if not findings["intents"]:
        findings["suggested_intent"] = {"name": "Reset a password", "description": "The user cannot sign in.",
                                        "evidence": [ref(prompt, r"^User:")]}
    return findings


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(database_url=f"sqlite:///{tmp_path / 'classify.db'}"))) as client:
        client.app.state.llm = FakeLLM(reviewer)
        yield client


def project(client):
    return client.post("/api/projects", json={"name": "Bank Agent"}).json()


def turn(client, p, session_id, event_id, args, result, minutes_ago=30):
    client.post("/api/v1/capture-session", json={"session_id": session_id, "user_data": {"user_id": f"user-{session_id}"}},
                headers={"x-org-id": p["id"]})
    stamp = int((utc_now() - timedelta(minutes=minutes_ago)).timestamp() * 1000)
    response = client.post("/api/v1/capture-event", headers={"x-org-id": p["id"]}, json={
        "event_id": event_id, "session_id": session_id, "primitive_name": "bank-agent",
        "args": args, "result": result, "timestamp": stamp, "latency": 500})
    assert response.status_code == 200, response.text


@pytest.fixture
def bank(client):
    p = project(client)
    base = f'/api/projects/{p["id"]}'
    assert client.post(f"{base}/intents", json={"name": "Get a refund", "description": "The user wants money back."}).status_code == 201
    policy = client.post(f"{base}/policies", json={"title": "Never reveal account numbers",
                                                   "description": "Mask all but the last four digits."})
    assert policy.status_code == 201, policy.text
    turn(client, p, "s-refund", "t1", "I want a refund for order 7", "Done. Refunded to account number is 4400123456.")
    turn(client, p, "s-login", "t2", "I can't log in to my account", "Let me send you a reset link.")
    return SimpleNamespace(project=p, base=base, policy=policy.json())


def test_policy_crud_and_versioning(client):
    p = project(client)
    base = f'/api/projects/{p["id"]}'
    assert client.post(f"{base}/policies", json={"title": "  "}).status_code == 422
    created = client.post(f"{base}/policies", json={"title": "Confirm identity", "severity": "critical"}).json()
    assert created["version"] == 1 and created["active"] and created["severity"] == "critical"
    assert client.patch(f'/api/policies/{created["id"]}', json={"severity": "low"}).json()["version"] == 1
    renamed = client.patch(f'/api/policies/{created["id"]}', json={"description": "Before any account change."}).json()
    assert renamed["version"] == 2 and renamed["severity"] == "low"
    assert [x["id"] for x in client.get(f"{base}/policies").json()] == [created["id"]]
    assert client.delete(f'/api/policies/{created["id"]}').json() == {"ok": True}
    assert client.get(f"{base}/policies").json() == []
    assert client.patch("/api/policies/missing", json={"active": False}).status_code == 404


def test_intents_accept_a_description_without_examples(client):
    base = f'/api/projects/{project(client)["id"]}'
    assert client.post(f"{base}/intents", json={"name": "Compare plans", "description": "Weighs two plans."}).status_code == 201
    assert client.post(f"{base}/intents", json={"name": "x", "examples": []}).status_code == 422


def test_llm_run_records_intents_violations_and_suggestions(client, bank):
    run = client.post(f"{bank.base}/classify", json={"range": "7d"}).json()
    assert run["classifier"] == "llm" and run["model"] == "fake-model"
    assert run["analyzed"] == 2 and run["errors"] == 0 and run["pending"] == 0 and run["policies_checked"]
    stats = client.get(f"{bank.base}/intent-stats").json()
    refund = next(i for i in stats["intents"] if i["name"] == "Get a refund")
    assert refund["conversations"] == 1 and refund["share"] == 50 and refund["last_seen"]
    assert stats["analyzed"] == 2 and stats["matched"] == 1 and stats["unmatched"] == 1
    assert stats["suggested"][0]["name"] == "Reset a password" and stats["suggested"][0]["conversations"] == 1
    violations = client.get(f"{bank.base}/violations").json()
    assert violations["violating_conversations"] == 1 and violations["violation_rate"] == 50
    assert violations["policies"][0]["violations"] == 1 and violations["policies"][0]["rate"] == 50
    evidence = client.get(f"{bank.base}/evidence", params={"kind": "policy", "target_id": bank.policy["id"]}).json()
    found = evidence["results"][0]
    assert found["reason"] == "The agent read out the full account number."
    assert found["session_id"] == "s-refund" and found["user_id"] == "user-s-refund"
    assert "account number is 4400123456" in found["messages"][0]["content"]
    suggested = client.get(f"{bank.base}/evidence", params={"kind": "suggested", "label": "reset a password"}).json()
    assert suggested["total"] == 1 and suggested["results"][0]["messages"][0]["role"] == "user"
    assert client.get(f"{bank.base}/evidence", params={"kind": "policy"}).status_code == 422
    # Violations join the problem list and flag the conversation.
    clusters = client.get("/api/clusters", params={"project_id": bank.project["id"]}).json()
    policy_cluster = next(c for c in clusters if c["kind"] == "policy_violation")
    assert policy_cluster["title"] == "A policy was not followed · Never reveal account numbers"
    detail = client.get(f'/api/clusters/{policy_cluster["id"]}').json()
    assert detail["evidence"][0]["reason"].startswith('Policy "Never reveal account numbers" was not followed.')
    status = client.get(f"{bank.base}/classify/status").json()
    assert status == {**status, "classifier": "llm", "llm_configured": True, "analyzed": 2, "conversations": 2}


def test_runs_skip_unchanged_conversations(client, bank):
    llm = client.app.state.llm
    client.post(f"{bank.base}/classify", json={})
    assert len(llm.calls) == 2
    again = client.post(f"{bank.base}/classify", json={}).json()
    assert again["analyzed"] == 0 and again["up_to_date"] == 2 and len(llm.calls) == 2
    turn(client, bank.project, "s-login", "t3", "Still locked out", "Try the link again.", minutes_ago=5)
    changed = client.post(f"{bank.base}/classify", json={}).json()
    assert changed["analyzed"] == 1 and changed["up_to_date"] == 1
    client.patch(f'/api/policies/{bank.policy["id"]}', json={"description": "Show only the last four digits."})
    reworded = client.post(f"{bank.base}/classify", json={"limit": 1}).json()
    assert reworded["analyzed"] == 1 and reworded["pending"] == 1
    assert client.post(f"{bank.base}/classify", json={"force": True}).json()["analyzed"] == 2


def test_unverifiable_model_output_is_discarded(client, bank):
    client.app.state.llm = FakeLLM(lambda prompt, tool: {
        "intents": [{"intent": "I9", "evidence": ["M1"]}, {"intent": "I1", "evidence": ["M99", "nonsense"]}],
        "violations": [{"policy": "P1", "evidence": ["M2"], "reason": ""}, {"policy": "P7", "evidence": ["M2"], "reason": "x"}],
    })
    run = client.post(f"{bank.base}/classify", json={}).json()
    assert run["analyzed"] == 2
    assert client.get(f"{bank.base}/intent-stats").json()["matched"] == 0
    assert client.get(f"{bank.base}/violations").json()["violating_conversations"] == 0


def test_llm_failures_are_recorded_and_stop_the_run(client, bank):
    def failing(prompt, tool):
        raise LLMError("llm_http_500")
    client.app.state.llm = FakeLLM(failing)
    for index in range(3):
        turn(client, bank.project, f"extra-{index}", f"x{index}", "Hello", "Hi")
    run = client.post(f"{bank.base}/classify", json={}).json()
    assert run["errors"] == 3 and run["analyzed"] == 0 and run["error_code"] == "llm_http_500"
    assert run["pending"] == 2  # stopped after three consecutive failures
    assert client.get(f"{bank.base}/classify/status").json()["errors"] == 3
    client.app.state.llm = FakeLLM(reviewer)
    assert client.post(f"{bank.base}/classify", json={}).json()["analyzed"] == 5


def test_without_an_llm_intents_use_examples_and_policies_wait(client):
    client.app.state.llm = None
    p = project(client)
    base = f'/api/projects/{p["id"]}'
    turn(client, p, "s-1", "t1", "I want a refund for my order", "Sure")
    note = client.post(f"{base}/classify", json={}).json()
    assert note["analyzed"] == 0 and "ANTHROPIC_API_KEY" in note["note"]
    client.post(f"{base}/intents", json={"name": "Get a refund", "examples": ["I want a refund for my order", "refund please"]})
    client.post(f"{base}/policies", json={"title": "Be polite"})
    run = client.post(f"{base}/classify", json={}).json()
    assert run["classifier"] == "examples" and run["analyzed"] == 1 and not run["policies_checked"]
    stats = client.get(f"{base}/intent-stats").json()
    assert stats["intents"][0]["conversations"] == 1
    assert client.get(f"{base}/violations").json()["policies_checked"] is False
    assert client.post(f"{base}/intents/suggest", json={}).status_code == 503
    assert client.post(f"{base}/intents/enrich", json={"name": "Get a refund"}).status_code == 503


def test_suggest_and_enrich_intents(client, bank):
    client.app.state.llm = FakeLLM(lambda prompt, tool: {
        "suggest_intents": {"intents": [{"name": "Get a refund", "description": "dupe"},
                                        {"name": "Reset a password", "description": "Locked out.", "examples": ["I can't log in"]},
                                        {"name": " ", "description": "blank"}]},
        "describe_intent": {"description": "The user asks for money back.", "examples": ["refund me", " ", "money back"]},
    }[tool])
    suggestions = client.post(f"{bank.base}/intents/suggest", json={"product_description": "A bank"}).json()
    assert [s["name"] for s in suggestions["suggestions"]] == ["Reset a password"]
    assert "<messages>" in client.app.state.llm.calls[0]["prompt"]
    enriched = client.post(f"{bank.base}/intents/enrich", json={"name": "Get a refund"}).json()
    assert enriched == {"name": "Get a refund", "description": "The user asks for money back.",
                        "examples": ["refund me", "money back"]}


def test_transcript_stays_within_budget():
    events = [SimpleNamespace(id=f"e{i}", role="user" if i % 2 else "assistant", name=None, status="success",
                              content="word " * 400, timestamp=utc_now() + timedelta(seconds=i), event_metadata={})
              for i in range(80)]
    text, refs = classify.transcript(events)
    assert len(text) <= classify.MAX_TRANSCRIPT_CHARS + 200
    assert "messages omitted" in text and "[M1]" in text and "[M80]" in text and len(refs) == 80


def test_org_projects_need_an_admin_to_change_policies(client):
    owner = client.post("/api/auth/signup", json={"email": "o@example.com", "password": "password-123"}).json()
    headers = {"Authorization": f'Bearer {owner["session"]}'}
    created = client.post(f'/api/orgs/{owner["organization"]["id"]}/projects', json={"name": "Shop"}, headers=headers).json()
    url = f'/api/projects/{created["id"]}/policies'
    assert client.post(url, json={"title": "Be polite"}).status_code == 401
    assert client.post(url, json={"title": "Be polite"}, headers=headers).status_code == 201
    assert len(client.get(url, headers=headers).json()) == 1


def test_deleting_a_project_removes_classification_data(client, bank):
    client.post(f"{bank.base}/classify", json={})
    assert client.delete(bank.base).json() == {"ok": True}
    assert client.get(f"{bank.base}/violations").status_code == 404
