from collections import defaultdict
from datetime import timedelta
from hashlib import sha256
import hmac
import re
import secrets
from typing import Literal
from uuid import UUID, uuid4, uuid5

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from starlette.responses import JSONResponse

from . import analysis
from .config import Settings
from .db import ClusterState, Event, Project, iso, make_database, utc, utc_now
from .demo import DEMO_PROJECT_ID, demo_events
from .mirror import mirror_events
from .schemas import ClusterPatch, EventBatch, ProjectInput

Range = Literal["24h", "7d", "30d"]


class RequestGuards:
    """Validate body size while streaming and protect every dashboard route."""
    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        path = scope.get("path", "")
        if path.startswith("/api/") and path != "/api/health" and self.settings.admin_token:
            provided = headers.get(b"authorization", b"")
            expected = f"Bearer {self.settings.admin_token}".encode()
            if not hmac.compare_digest(provided, expected):
                return await JSONResponse({"detail": "Administrator token required"}, status_code=401)(scope, receive, send)
        body = bytearray()
        if scope["method"] in ("POST", "PUT", "PATCH"):
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > self.settings.max_body_bytes:
                    return await JSONResponse({"detail": "Request body exceeds size limit"}, status_code=413)(scope, receive, send)
                if not message.get("more_body", False):
                    break
            delivered = False
            async def buffered_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()
            return await self.app(scope, buffered_receive, send)
        return await self.app(scope, receive, send)


def project_dict(project):
    return {"id": project.id, "name": project.name, "slug": project.slug,
            "created_at": iso(project.created_at), "is_demo": project.is_demo}


def create_project(session, name, *, id=None, is_demo=False):
    id = id or str(uuid4())
    key = "tvk_" + secrets.token_urlsafe(32)
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"
    project = Project(id=id, name=name, slug=f"{slug[:110]}-{id[:8]}", api_key=key,
                      key_hash=sha256(key.encode()).hexdigest(), is_demo=is_demo)
    session.add(project)
    session.flush()
    return project


def persist_events(session, engine, project_id, events):
    insert = sqlite_insert if engine.dialect.name == "sqlite" else postgres_insert
    accepted, duplicates, mirror = 0, 0, []
    for event in events:
        values = event.model_dump()
        values["source_conversation_id"] = values.pop("conversation_id")
        values["conversation_id"] = str(uuid5(UUID(project_id), values["source_conversation_id"]))
        values["event_metadata"] = values.pop("metadata")
        values["timestamp"] = utc(values["timestamp"])
        values["project_id"] = project_id
        # psycopg can report rowcount=-1 for this execution mode. RETURNING
        # distinguishes an inserted row from a skipped conflict on both adapters.
        inserted_id = session.execute(insert(Event).values(**values).on_conflict_do_nothing(
            index_elements=["project_id", "id"]).returning(Event.id)).scalar_one_or_none()
        if inserted_id is not None:
            accepted += 1
            mirror.append({"project_id": project_id, "id": values["id"],
                           "conversation_id": values["conversation_id"], "datetime": values["timestamp"],
                           "role": values["role"], "payload": event.model_dump(mode="json")})
        else:
            duplicates += 1
    return accepted, duplicates, mirror


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()
    engine, sessions = make_database(settings.database_url)
    app = FastAPI(title="Tervik API", version="0.1.0")
    app.state.engine = engine
    app.state.sessions = sessions
    app.state.settings = settings
    app.add_middleware(RequestGuards, settings=settings)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST", "PATCH"], allow_headers=["Authorization", "Content-Type"])

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # Avoid echoing conversation contents or non-finite JSON input in error responses.
        details = [{"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
                   for item in error.errors()]
        return JSONResponse(status_code=422, content={"detail": details})

    def get_project(session, project_id):
        project = session.get(Project, project_id) if project_id else session.scalars(
            select(Project).order_by(Project.created_at, Project.id)).first()
        if project is None:
            raise HTTPException(404, "Project not found. Create a project or seed the demo workspace.")
        return project

    def project_analysis(session, project_id):
        events = list(session.scalars(select(Event).where(Event.project_id == project_id)
                                      .order_by(Event.timestamp, Event.id)))
        states = {state.id: state.status for state in session.scalars(
            select(ClusterState).where(ClusterState.project_id == project_id))}
        return events, analysis.analyze(events), states

    def window(range):
        end = utc_now()
        return end - timedelta(hours={"24h": 24, "7d": 168, "30d": 720}[range]), end

    def locate_cluster(session, id, range):
        start, end = window(range)
        for project in session.scalars(select(Project)):
            events, signals, states = project_analysis(session, project.id)
            related = [s for s in signals if s["cluster_id"] == id and utc(s["event"].timestamp) <= end]
            if not related:
                continue
            rows = analysis.clusters(project.id, events, signals, states, start, end)
            row = next((row for row in rows if row["id"] == id), None)
            if row is None:
                oldest = min(utc(e.timestamp) for e in events)
                row = next(row for row in analysis.clusters(project.id, events, signals, states, oldest, end) if row["id"] == id)
                row.update(count=0, affected_users=0, share=0, trend=0)
            selected = analysis.signals_in_range(related, start, end)
            selected_events = analysis.in_range(events, start, end)
            ids = {signal["conversation_id"] for signal in selected}
            conversations = [s for s in analysis.conversation_summaries(selected_events, analysis.signals_in_range(signals, start, end)) if s["id"] in ids]
            evidence = [{"event_id": signal["event_id"], "conversation_id": signal["conversation_id"],
                         "content": signal["event"].content, "reason": signal["reason"]} for signal in selected]
            return row, conversations, evidence
        raise HTTPException(404, "Cluster not found")

    @app.get("/api/health")
    def health():
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        return {"status": "ok", "storage": engine.dialect.name, "analysis_mode": analysis.ANALYSIS_MODE}

    @app.get("/api/projects")
    def projects():
        with sessions() as session:
            return [project_dict(p) for p in session.scalars(select(Project).order_by(Project.created_at, Project.id))]

    @app.post("/api/projects", status_code=201)
    def new_project(body: ProjectInput):
        with sessions.begin() as session:
            project = create_project(session, body.name)
            return {**project_dict(project), "api_key": project.api_key}

    @app.get("/api/projects/{id}/key")
    def project_key(id: str):
        with sessions() as session:
            return {"api_key": get_project(session, id).api_key}

    @app.post("/v1/events")
    def ingest(body: EventBatch, request: Request, background_tasks: BackgroundTasks):
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            raise HTTPException(401, "Project ingest key required")
        key_hash = sha256(header[len("Bearer "):].encode()).hexdigest()
        with sessions.begin() as session:
            project = session.scalars(select(Project).where(Project.key_hash == key_hash)).first()
            if project is None:
                raise HTTPException(401, "Invalid project ingest key")
            accepted, duplicates, mirror = persist_events(session, engine, project.id, body.events)
        if settings.clickhouse_url:
            background_tasks.add_task(mirror_events, settings, mirror)
        return {"accepted": accepted, "duplicates": duplicates}

    @app.get("/api/overview")
    def overview(project_id: str | None = None, range: Range = "7d"):
        with sessions() as session:
            project = get_project(session, project_id)
            events, signals, states = project_analysis(session, project.id)
            start, end = window(range)
            rows = analysis.clusters(project.id, events, signals, states, start, end)
            return analysis.overview(project_dict(project), events, signals, rows, start, end)

    @app.get("/api/clusters")
    def clusters(project_id: str | None = None, range: Range = "7d", search: str | None = Query(default=None, max_length=200),
                 status: Literal["open", "resolved"] | None = None):
        with sessions() as session:
            project = get_project(session, project_id)
            events, signals, states = project_analysis(session, project.id)
            start, end = window(range)
            rows = analysis.clusters(project.id, events, signals, states, start, end)
            return [row for row in rows if (not status or row["status"] == status) and
                    (not search or search.casefold() in (row["title"] + " " + row["description"]).casefold())]

    @app.get("/api/clusters/{id}")
    def cluster(id: str, range: Range = "7d"):
        with sessions() as session:
            row, conversations, evidence = locate_cluster(session, id, range)
            return {**row, "conversations": conversations, "evidence": evidence}

    @app.patch("/api/clusters/{id}")
    def update_cluster(id: str, body: ClusterPatch):
        with sessions.begin() as session:
            row, _, _ = locate_cluster(session, id, "7d")
            insert = sqlite_insert if engine.dialect.name == "sqlite" else postgres_insert
            session.execute(insert(ClusterState).values(id=id, project_id=row["project_id"], status=body.status)
                            .on_conflict_do_update(index_elements=["id"], set_={"status": body.status}))
            row["status"] = body.status
            return row

    @app.get("/api/conversations")
    def conversations(project_id: str | None = None, range: Range = "7d", search: str | None = Query(default=None, max_length=200),
                      flagged: bool | None = None):
        with sessions() as session:
            project = get_project(session, project_id)
            events, signals, _ = project_analysis(session, project.id)
            start, end = window(range)
            rows = analysis.conversation_summaries(analysis.in_range(events, start, end), analysis.signals_in_range(signals, start, end))
            matching_ids = {e.conversation_id for e in analysis.in_range(events, start, end)
                            if search and search.casefold() in e.content.casefold()}
            return [row for row in rows if (flagged is None or (row["status"] == "flagged") == flagged) and
                    (not search or row["id"] in matching_ids or search.casefold() in (row["user_id"] or "").casefold())]

    @app.get("/api/conversations/{id}")
    def conversation(id: str):
        with sessions() as session:
            events = list(session.scalars(select(Event).where(Event.conversation_id == id).order_by(Event.timestamp, Event.id)))
            if not events:
                raise HTTPException(404, "Conversation not found")
            signals = analysis.analyze(events)
            return {**analysis.summary(events, signals), "messages": [analysis.event_dict(e) for e in events],
                    "signals": [analysis.public_signal(s) for s in signals], "spans": analysis.spans(events)}

    @app.post("/api/demo/seed")
    def seed_demo(background_tasks: BackgroundTasks):
        if not settings.demo_enabled:
            raise HTTPException(404, "Demo seeding is disabled")
        with sessions.begin() as session:
            project = session.get(Project, DEMO_PROJECT_ID)
            if project is None:
                # The PK conflict is handled by the database for concurrent requests.
                key = "tvk_" + secrets.token_urlsafe(32)
                insert = sqlite_insert if engine.dialect.name == "sqlite" else postgres_insert
                session.execute(insert(Project).values(id=DEMO_PROJECT_ID, name="Sample workspace", slug="sample-workspace",
                    created_at=utc_now(), is_demo=True, api_key=key, key_hash=sha256(key.encode()).hexdigest())
                    .on_conflict_do_nothing(index_elements=["id"]))
            accepted, _, mirror = persist_events(session, engine, DEMO_PROJECT_ID, demo_events(utc_now()))
        if settings.clickhouse_url:
            background_tasks.add_task(mirror_events, settings, mirror)
        return {"seeded": accepted > 0, "project_id": DEMO_PROJECT_ID}

    return app


app = create_app()
