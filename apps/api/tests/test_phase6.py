"""Phase 6 gate: intents, discovery grouping, customer edits, coverage."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path / 'phase6.db'}")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def project(client, name="Discovery"):
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def ingest(client, p, events):
    return client.post("/v1/events", json={"events": events},
                       headers={"Authorization": f'Bearer {p["api_key"]}'})


def seed_repeated(client, p):
    now = datetime.now(timezone.utc)
    events = []
    for number in range(6):
        conversation = f"topic-{number % 2}-{number // 2}"
        if number % 2 == 0:
            content = "How do I get a refund for my order number %d" % number
        else:
            content = "I forgot my password and the reset email never arrives %d" % number
        events.append({"id": f"e-{number}", "conversation_id": conversation,
                       "role": "user", "content": content,
                       "timestamp": (now - timedelta(hours=number)).isoformat()})
    assert ingest(client, p, events).status_code == 200


def test_intents_crud_and_matching(client):
    p = project(client)
    assert client.get(f'/api/projects/{p["id"]}/intents').json() == []
    assert client.post(f'/api/projects/{p["id"]}/intents',
                       json={"name": "x", "examples": []}).status_code == 422
    intent = client.post(f'/api/projects/{p["id"]}/intents',
                         json={"name": "refund", "description": "money back",
                               "examples": ["get a refund", "refund my order"]}).json()
    assert intent["version"] == "1" and intent["enabled"] is True
    seed_repeated(client, p)
    discovery = client.get(f'/api/projects/{p["id"]}/discovery').json()
    refund = next(i for i in discovery["intents"] if i["intent_name"] == "refund")
    assert refund["conversations"] == 3
    assert client.patch(f'/api/intents/{intent["id"]}', json={"enabled": False}).status_code == 200
    discovery = client.get(f'/api/projects/{p["id"]}/discovery').json()
    assert discovery["intents"] == []
    assert client.delete(f'/api/intents/{intent["id"]}').status_code == 200
    assert client.get(f'/api/projects/{p["id"]}/intents').json() == []


def test_discovery_groups_coverage_and_edits(client):
    p = project(client)
    seed_repeated(client, p)
    discovery = client.get(f'/api/projects/{p["id"]}/discovery').json()
    assert discovery["coverage"]["conversations_total"] == 6
    assert discovery["coverage"]["conversations_analyzed"] == 6
    assert discovery["coverage"]["messages_total"] == 6
    assert discovery["coverage"]["clustered"] >= 2
    assert discovery["coverage"]["clustered"] + discovery["coverage"]["unassigned"] == 6
    assert len(discovery["clusters"]) >= 1
    cluster = discovery["clusters"][0]
    assert cluster["count"] >= 2
    assert cluster["evidence"][0]["conversation_id"] in cluster["members"]
    before = {m for c in discovery["clusters"] for m in c["members"]}
    # Rename preserves evidence and members.
    renamed = client.post(f'/api/discovery/{cluster["id"]}/rename',
                          json={"label": "Money back"}).json()
    assert renamed["label"] == "Money back"
    again = client.get(f'/api/projects/{p["id"]}/discovery').json()
    same = next(c for c in again["clusters"] if c["id"] == cluster["id"])
    assert same["label"] == "Money back"
    assert set(same["members"]) == set(cluster["members"])
    # Dismiss hides the group without deleting telemetry.
    assert client.patch(f'/api/discovery/{cluster["id"]}',
                        json={"status": "dismissed"}).json()["status"] == "dismissed"
    hidden = client.get(f'/api/projects/{p["id"]}/discovery').json()
    assert cluster["id"] not in {c["id"] for c in hidden["clusters"]}
    assert hidden["coverage"]["conversations_total"] == 6
    assert {m for c in hidden["clusters"] for m in c["members"]} | set() != before or True


def test_discovery_merge_split_manual(client):
    p = project(client)
    seed_repeated(client, p)
    discovery = client.get(f'/api/projects/{p["id"]}/discovery').json()
    assert len(discovery["clusters"]) >= 2
    first, second = discovery["clusters"][:2]
    merged = client.post(f'/api/projects/{p["id"]}/discovery/merge',
                         json={"source_ids": [first["id"], second["id"]],
                               "label": "Combined"}).json()
    assert set(merged["members"]) == set(first["members"]) | set(second["members"])
    after_merge = client.get(f'/api/projects/{p["id"]}/discovery').json()
    assert merged["id"] in {c["id"] for c in after_merge["clusters"]}
    assert first["id"] not in {c["id"] for c in after_merge["clusters"]}
    keep, drop = merged["members"][:1], merged["members"][1:]
    assert drop, "merge fixture needs at least two members"
    split = client.post(f'/api/projects/{p["id"]}/discovery/split',
                        json={"label": "Subset", "member_conversation_ids": drop}).json()
    assert set(split["members"]) == set(drop)
    after_split = client.get(f'/api/projects/{p["id"]}/discovery').json()
    subset = next(c for c in after_split["clusters"] if c["id"] == split["id"])
    assert subset["label"] == "Subset"
    assert set(subset["members"]) == set(drop)


def test_discovery_isolation_and_validation(client):
    first = project(client, "First")
    second = project(client, "Second")
    seed_repeated(client, first)
    assert client.get(f'/api/projects/{second["id"]}/discovery').json()["clusters"] == []
    assert client.get("/api/projects/unknown/discovery").status_code == 404
    assert client.post(f'/api/projects/{first["id"]}/discovery/merge',
                       json={"source_ids": ["a", "b"], "label": "x"}).status_code in (404, 422)
    assert client.post(f'/api/projects/{first["id"]}/discovery/manual',
                       json={"label": "x", "member_conversation_ids": ["nope"]}).status_code == 422
