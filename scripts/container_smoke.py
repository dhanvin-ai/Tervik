"""Verify a running local Compose stack without printing credentials or retaining test data."""

from pathlib import Path
import json
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
environment_file = ROOT / ".env.docker"
if not environment_file.exists():
    raise SystemExit("Run python3 scripts/configure_docker.py and start the Compose stack first.")
environment = dict(line.split("=", 1) for line in environment_file.read_text().splitlines() if line and not line.startswith("#") and "=" in line)
base = "http://127.0.0.1:" + environment.get("TERVIK_API_PORT", "8001")
compose = ["docker", "compose", "--env-file", ".env.docker"]
project_ids = []


def request(route, *, method="GET", body=None, key=None, status=200):
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + (key or environment["TERVIK_ADMIN_TOKEN"])}
    operation = Request(base + route, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
    try:
        response = urlopen(operation, timeout=10)
    except HTTPError as error:
        response = error
    assert response.status == status, f"{method} {route}: expected {status}, got {response.status}"
    return json.load(response)


def container(code, *args):
    result = subprocess.run(compose + ["exec", "-T", "api", "python", "-c", code, *args], cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Container verification command failed; inspect the API container's configuration.")
    return result.stdout.strip()


mirror_query = """
import os, sys, clickhouse_connect
client = clickhouse_connect.get_client(host='clickhouse', username=os.environ['CLICKHOUSE_USER'], password=os.environ['CLICKHOUSE_PASSWORD'])
try:
    count = client.query('SELECT count() FROM tervik.events WHERE project_id = {project:String}', parameters={'project': sys.argv[1]}).first_row[0]
    print(count)
finally:
    client.close()
"""

try:
    assert request("/api/health")["storage"] == "postgresql"
    project = request("/api/projects", method="POST", body={"name": "Container verification " + str(uuid4())[:8]}, status=201)
    project_ids.append(project["id"])
    events = [
        {"id": "container-user", "conversation_id": "verification", "user_id": "test-user", "role": "user", "content": "Look up the current plan limit."},
        {"id": "container-tool", "conversation_id": "verification", "user_id": "test-user", "role": "tool", "content": "Connection unavailable", "status": "error", "name": "lookup_plan", "span_id": "tool", "parent_span_id": "turn", "latency_ms": 20},
        {"id": "container-assistant", "conversation_id": "verification", "user_id": "test-user", "role": "assistant", "content": "I could not reach the plan service.", "span_id": "turn", "latency_ms": 30},
        {"id": "container-correction", "conversation_id": "verification", "user_id": "test-user", "role": "user", "content": "That's wrong; the plan details are already in the context."},
    ]
    assert request("/v1/events", method="POST", body={"events": events}, key=project["api_key"]) == {"accepted": 4, "duplicates": 0}
    assert request("/v1/events", method="POST", body={"events": events}, key=project["api_key"]) == {"accepted": 0, "duplicates": 4}
    request("/api/projects", key=project["api_key"], status=401)
    request("/v1/events", method="POST", body={"events": [{"conversation_id": "invalid", "role": "user", "content": "valid"}, {"conversation_id": "invalid", "role": "unknown", "content": "invalid"}]}, key=project["api_key"], status=422)
    overview = request("/api/overview?project_id=" + project["id"])
    assert overview["metrics"]["messages"] == 4
    assert overview["metrics"]["conversations"] == 1
    assert overview["metrics"]["failure_rate"] == 100
    for attempt in range(30):
        try:
            if int(container(mirror_query, project["id"])) == 4:
                break
        except RuntimeError:
            pass
        time.sleep(0.25)
    else:
        raise AssertionError("Accepted events did not reach the ClickHouse mirror.")
    print("PASS: PostgreSQL ingestion, atomic validation, scoped keys, deduplication, dashboard queries, and ClickHouse mirror.")
finally:
    if project_ids:
        cleanup = """
import os, sys, clickhouse_connect
from sqlalchemy import delete
from app.db import Project, Event, ClusterState
from app.main import app
with app.state.sessions.begin() as session:
    session.execute(delete(ClusterState).where(ClusterState.project_id.in_(sys.argv[1:])))
    session.execute(delete(Event).where(Event.project_id.in_(sys.argv[1:])))
    session.execute(delete(Project).where(Project.id.in_(sys.argv[1:])))
client = clickhouse_connect.get_client(host='clickhouse', username=os.environ['CLICKHOUSE_USER'], password=os.environ['CLICKHOUSE_PASSWORD'])
try:
    for project in sys.argv[1:]:
        client.command('ALTER TABLE tervik.events DELETE WHERE project_id = {project:String}', parameters={'project': project}, settings={'mutations_sync': 1})
finally:
    client.close()
"""
        container(cleanup, *project_ids)
