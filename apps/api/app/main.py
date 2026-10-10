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
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from starlette.responses import JSONResponse

from . import analysis
from . import otlp as otlp_mod
from . import queue as queue_mod
from . import alerts as alerts_mod
from . import evaluate as evaluate_mod
from . import improve as improve_mod
from . import mcp as mcp_mod
from . import capture_v1 as capture_mod
from . import insights as insights_mod
from .auth import (ROLES, SESSION_PREFIX, add_membership, create_organization,
                   create_session, credential_for_token, hash_password, is_ingest_token,
                   new_ingest_key, normalize_email, project_role, require_project_role,
                   resolve_session, sha256_hex, verify_password)
from .capture import project_settings
from .config import Settings
from .db import (Account, AlertDelivery, AlertRule, AuditRecord, BehaviorRule, ClusterState, ConversationSession, Credential, EndUser, Environment,
                 EvalDataset, EvalRun, Event, Improvement, IngestionJob,
                 Intent, Membership, Organization, PayloadObject, Plan, Project, PromptVersion, SemanticCluster, SemanticMembership, Session, UsageRecord,
                 iso, make_database, utc, utc_now)
from .demo import DEMO_PROJECT_ID, demo_events
from .mirror import mirror_events
from .schemas import (AgentDescriptor, AlertRuleInput, AlertRulePatch, CaptureInput, ClusterPatch, CredentialInput, DiscoveryMembers, DiscoveryMerge,
                      DiscoveryRename, DiscoveryStatus, EvalCase, EvalDatasetInput, EvalDatasetPatch, EvalRunInput, EventBatch, FindingsDatasetInput, ImprovementEval, ImprovementInput, ImprovementTransition, IntentInput,
                      IntentPatch, LoginInput,
                      MemberInput, MemberPatch, OrgInput, OrgProjectInput, ProjectInput, RuleInput,
                      RulePatch, SignupInput)

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
        if path.startswith("/api/") and path != "/api/health" and not path.startswith("/api/v1/") and self.settings.admin_token:
            provided = headers.get(b"authorization", b"")
            expected = f"Bearer {self.settings.admin_token}".encode()
            if hmac.compare_digest(provided, expected):
                pass
            elif provided.decode("latin1").startswith(f"Bearer {SESSION_PREFIX}"):
                # Phase 2 session tokens pass through; route handlers enforce membership.
                pass
            elif not hmac.compare_digest(provided, expected):
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
    data = {"id": project.id, "name": project.name, "slug": project.slug,
            "created_at": iso(project.created_at), "is_demo": project.is_demo}
    if getattr(project, "org_id", None):
        data["org_id"] = project.org_id
    return data


def audit(session, org_id, action, resource="", account_id=None):
    session.add(AuditRecord(id=str(uuid4()), org_id=org_id, account_id=account_id,
                            action=action, resource=resource))


def month_start(now):
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_usage(session, org_id):
    """Accepted events this calendar month across the org's projects."""
    start = month_start(utc_now())
    project_ids = list(session.scalars(select(Project.id).where(Project.org_id == org_id)))
    if not project_ids:
        return 0
    return session.execute(select(func.count()).select_from(UsageRecord).where(
        UsageRecord.project_id.in_(project_ids), UsageRecord.created_at >= start)).scalar_one()


def ensure_plan(session, org_id):
    plan = session.get(Plan, org_id)
    if plan is None:
        plan = Plan(org_id=org_id, name="beta", monthly_event_limit=100000)
        session.add(plan)
        session.flush()
    return plan


def check_quota(session, project):
    """Paid-beta plan enforcement. Legacy projects without orgs are exempt."""
    if not project.org_id:
        return
    plan = ensure_plan(session, project.org_id)
    if month_usage(session, project.org_id) >= plan.monthly_event_limit:
        raise HTTPException(429, "Monthly event quota exceeded for this organization")


def session_auth(request, session):
    """Resolve a Phase 2 session from the request, or None."""
    header = request.headers.get("authorization", "")
    if not header.startswith(f"Bearer {SESSION_PREFIX}"):
        return None
    return resolve_session(session, header[len("Bearer "):])


def require_session(request, session):
    resolved = session_auth(request, session)
    if resolved is None:
        raise HTTPException(401, "Login required")
    return resolved


def org_membership(session, org_id, account_id):
    membership = session.get(Membership, (org_id, account_id))
    if membership is None:
        raise HTTPException(404, "Organization not found")
    return membership


def org_project(session, project_id, account_id, minimum="viewer"):
    project = session.get(Project, project_id)
    if project is None or not project.org_id:
        raise HTTPException(404, "Project not found")
    membership = session.get(Membership, (project.org_id, account_id))
    if membership is None:
        raise HTTPException(404, "Project not found")
    try:
        require_project_role(session, project, account_id, minimum)
    except PermissionError:
        raise HTTPException(403, "Insufficient role")
    return project


def resolve_ingest(request, session):
    """Resolve an ingest credential to (project, environment). Legacy keys included."""
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, "Project ingest key required")
    return ingest_secret(session, header[len("Bearer "):])


def resolve_capture(request, session):
    """Resolve a capture API caller to (project, environment).

    Accepts the project ingest key (`Authorization: Bearer` or `x-api-key`) or
    the project ID in `x-org-id`. The ID is a public, write-only routing
    identifier, like a browser analytics key: it can add events but never read
    them, and a project can turn it off with the `public_ingest` setting.
    """
    if request.headers.get("authorization", "").startswith("Bearer "):
        return resolve_ingest(request, session)[:2]
    api_key = request.headers.get("x-api-key", "").strip()
    if api_key:
        return ingest_secret(session, api_key)[:2]
    org_id = request.headers.get("x-org-id", "").strip()
    if not org_id:
        raise HTTPException(401, "Send the project ID in x-org-id, or a project ingest key")
    project = session.get(Project, org_id)
    if project is None or not project_settings(project).get("public_ingest", True):
        raise HTTPException(401, "Unknown project ID, or public ingestion is turned off for it")
    return project, "production"


def ingest_secret(session, secret):
    key_hash = sha256_hex(secret)
    project = session.scalars(select(Project).where(Project.key_hash == key_hash)).first()
    if project is not None:
        return project, "production", None
    credential = session.scalars(select(Credential).where(Credential.key_hash == key_hash)).first()
    if credential is None or credential.revoked_at is not None:
        raise HTTPException(401, "Invalid project ingest key")
    project = session.get(Project, credential.project_id)
    if project is None:
        raise HTTPException(401, "Invalid project ingest key")
    environment = "production"
    if credential.environment_id:
        env = session.get(Environment, credential.environment_id)
        if env is not None:
            environment = env.name
    return project, environment, credential


def create_project(session, name, *, id=None, is_demo=False, org_id=None):
    id = id or str(uuid4())
    key = "tvk_" + secrets.token_urlsafe(32)
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"
    project = Project(id=id, name=name, slug=f"{slug[:110]}-{id[:8]}", api_key=key,
                      key_hash=sha256(key.encode()).hexdigest(), is_demo=is_demo,
                      org_id=org_id, settings={})
    session.add(project)
    session.flush()
    return project


def ensure_environment(session, project_id, name="production"):
    env = session.scalars(select(Environment).where(
        Environment.project_id == project_id, Environment.name == name)).first()
    if env is None:
        env = Environment(id=str(uuid4()), project_id=project_id, name=name)
        session.add(env)
        session.flush()
    return env


def mint_credential(session, project_id, environment_id, name, account_id):
    secret, prefix, key_hash = new_ingest_key()
    record = Credential(id=str(uuid4()), project_id=project_id, environment_id=environment_id,
                        name=name, prefix=prefix, key_hash=key_hash, scope="ingest",
                        created_by=account_id)
    session.add(record)
    session.flush()
    return record, secret


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
                       allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "x-org-id", "x-api-key"])

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
        rules = list(session.scalars(select(BehaviorRule).where(
            BehaviorRule.project_id == project_id, BehaviorRule.enabled == True)))  # noqa: E712
        return events, analysis.analyze(events, rules), states

    def window(range):
        end = utc_now()
        return end - timedelta(hours={"24h": 24, "7d": 168, "30d": 720}[range]), end

    def dashboard_access(request: Request, db_session, project):
        """Org isolation for session callers. Legacy projects stay isolated from sessions."""
        header = request.headers.get("authorization", "")
        if header.startswith("Bearer tvk_"):
            raise HTTPException(401, "Ingest keys cannot read customer data")
        resolved = session_auth(request, db_session)
        if project.org_id is None:
            if resolved is not None:
                raise HTTPException(404, "Project not found")
            return None
        if resolved is None:
            return None
        _, account = resolved
        membership = db_session.get(Membership, (project.org_id, account.id))
        if membership is None:
            raise HTTPException(404, "Project not found")
        return membership

    def locate_cluster(db_session, id, range, request: Request | None = None):
        start, end = window(range)
        for project in db_session.scalars(select(Project)):
            if request is not None:
                try:
                    dashboard_access(request, db_session, project)
                except HTTPException:
                    continue
            events, signals, states = project_analysis(db_session, project.id)
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

    @app.get("/api/compat")
    def compat():
        """Minimum supported SDK versions. Older clients keep working on the
        stable v2 event contract; this advertises the tested floor."""
        return {"event_contract": "events-v2",
                "minimum_clients": {"@tervik/sdk": "0.1.0", "tervik": "0.1.0",
                                    "tervik-node": "0.1.0", "tervik-python": "0.1.0"},
                "deprecated": []}

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
        with sessions.begin() as session:
            project, environment, _ = resolve_ingest(request, session)
            check_quota(session, project)
            accepted, duplicates, _ = queue_mod.enqueue_events(
                session, engine, project, body.events, environment=environment)
        if settings.inline_process:
            with sessions.begin() as session:
                queue_mod.process_pending(session, engine, settings, project_id=project.id)
            if settings.clickhouse_url:
                background_tasks.add_task(retry_mirrors_task, project.id)
        return {"accepted": accepted, "duplicates": duplicates}

    def retry_mirrors_task(project_id: str):
        with sessions.begin() as session:
            queue_mod.retry_mirrors(session, settings, limit=500)

    @app.post("/v1/otlp/traces")
    async def ingest_otlp(request: Request, background_tasks: BackgroundTasks):
        raw = await request.body()
        try:
            import json as json_lib
            body = json_lib.loads(raw.decode("utf-8"))
        except Exception:
            raise HTTPException(400, "Invalid OTLP JSON body")
        with sessions.begin() as session:
            project, environment, _ = resolve_ingest(request, session)
            check_quota(session, project)
            normalized = otlp_mod.normalize_otlp_traces(body if isinstance(body, dict) else {})
            if not normalized:
                raise HTTPException(422, "No spans found in OTLP payload")
            if len(normalized) > 100:
                raise HTTPException(422, "OTLP batch exceeds 100 spans")
            from .schemas import EventInput
            from pydantic import ValidationError as PydanticValidationError
            try:
                inputs = [EventInput(**item) for item in normalized]
            except PydanticValidationError as error:
                raise HTTPException(422, f"Invalid OTLP span data: {error.errors()[0]['msg']}")
            accepted, duplicates, _ = queue_mod.enqueue_events(
                session, engine, project, inputs, environment=environment)
        if settings.inline_process:
            with sessions.begin() as session:
                queue_mod.process_pending(session, engine, settings, project_id=project.id)
        return {"accepted": accepted, "duplicates": duplicates}

    # ---- Session and event capture API ----

    def capture_after_commit(project_id, background_tasks):
        if settings.inline_process:
            with sessions.begin() as session:
                queue_mod.process_pending(session, engine, settings, project_id=project_id)
            if settings.clickhouse_url:
                background_tasks.add_task(retry_mirrors_task, project_id)

    @app.post("/api/v1/capture-session")
    def capture_session(body: capture_mod.SessionCapture, request: Request):
        with sessions.begin() as session:
            project, _ = resolve_capture(request, session)
            capture_mod.upsert_session(session, project.id, body)
        return {"session_id": body.session_id}

    @app.post("/api/v1/capture-event")
    def capture_event(body: capture_mod.EventCapture, request: Request, background_tasks: BackgroundTasks):
        with sessions.begin() as session:
            project, environment = resolve_capture(request, session)
            check_quota(session, project)
            row = capture_mod.implicit_session(session, project.id, body.session_id,
                                               capture_mod.from_millis(body.timestamp))
            trace_id = capture_mod.resolve_trace(session, project.id, body.parent_id, body.event_id)
            try:
                events = capture_mod.to_events(body, row, trace_id)
            except ValueError as error:
                raise HTTPException(422, str(error).splitlines()[0])
            queue_mod.enqueue_events(session, engine, project, events, environment=environment)
        capture_after_commit(project.id, background_tasks)
        with sessions.begin() as session:
            capture_mod.reroot_children(session, project.id, body.event_id, trace_id)
        return {"event_id": body.event_id}

    @app.get("/api/overview")
    def overview(request: Request, project_id: str | None = None, range: Range = "7d"):
        with sessions() as session:
            project = get_project(session, project_id)
            dashboard_access(request, session, project)
            events, signals, states = project_analysis(session, project.id)
            start, end = window(range)
            rows = analysis.clusters(project.id, events, signals, states, start, end)
            return analysis.overview(project_dict(project), events, signals, rows, start, end)

    @app.get("/api/clusters")
    def clusters(request: Request, project_id: str | None = None, range: Range = "7d", search: str | None = Query(default=None, max_length=200),
                 status: Literal["open", "resolved"] | None = None):
        with sessions() as session:
            project = get_project(session, project_id)
            dashboard_access(request, session, project)
            events, signals, states = project_analysis(session, project.id)
            start, end = window(range)
            rows = analysis.clusters(project.id, events, signals, states, start, end)
            return [row for row in rows if (not status or row["status"] == status) and
                    (not search or search.casefold() in (row["title"] + " " + row["description"]).casefold())]

    @app.get("/api/clusters/{id}")
    def cluster(request: Request, id: str, range: Range = "7d"):
        with sessions() as session:
            row, conversations, evidence = locate_cluster(session, id, range, request)
            return {**row, "conversations": conversations, "evidence": evidence}

    @app.patch("/api/clusters/{id}")
    def update_cluster(request: Request, id: str, body: ClusterPatch):
        with sessions.begin() as session:
            row, _, _ = locate_cluster(session, id, "7d", request)
            membership = None
            project = session.get(Project, row["project_id"])
            if project is not None and project.org_id is not None:
                resolved = session_auth(request, session)
                if resolved is None:
                    pass  # legacy/admin path
                else:
                    membership = dashboard_access(request, session, project)
                    require_project_role(session, project, resolved[1].id, "member")
            insert = sqlite_insert if engine.dialect.name == "sqlite" else postgres_insert
            session.execute(insert(ClusterState).values(id=id, project_id=row["project_id"], status=body.status)
                            .on_conflict_do_update(index_elements=["id"], set_={"status": body.status}))
            row["status"] = body.status
            return row

    @app.get("/api/conversations")
    def conversations(request: Request, project_id: str | None = None, range: Range = "7d", search: str | None = Query(default=None, max_length=200),
                      flagged: bool | None = None):
        with sessions() as session:
            project = get_project(session, project_id)
            dashboard_access(request, session, project)
            events, signals, _ = project_analysis(session, project.id)
            start, end = window(range)
            rows = analysis.conversation_summaries(analysis.in_range(events, start, end), analysis.signals_in_range(signals, start, end))
            matching_ids = {e.conversation_id for e in analysis.in_range(events, start, end)
                            if search and search.casefold() in e.content.casefold()}
            return [row for row in rows if (flagged is None or (row["status"] == "flagged") == flagged) and
                    (not search or row["id"] in matching_ids or search.casefold() in (row["user_id"] or "").casefold())]

    @app.get("/api/conversations/{id}")
    def conversation(request: Request, id: str):
        with sessions() as session:
            events = list(session.scalars(select(Event).where(Event.conversation_id == id).order_by(Event.timestamp, Event.id)))
            if not events:
                raise HTTPException(404, "Conversation not found")
            project = session.get(Project, events[0].project_id)
            if project is not None:
                dashboard_access(request, session, project)
            rules = list(session.scalars(select(BehaviorRule).where(
                BehaviorRule.project_id == events[0].project_id, BehaviorRule.enabled == True)))  # noqa: E712
            signals = analysis.analyze(events, rules)
            captured = session.get(ConversationSession, (events[0].project_id, events[0].source_conversation_id))
            profile = session.get(EndUser, (events[0].project_id, captured.user_id)) if captured and captured.user_id else None
            return {**analysis.summary(events, signals), "messages": [analysis.event_dict(e) for e in events],
                    "signals": [analysis.public_signal(s) for s in signals], "spans": analysis.spans(events),
                    "session": None if captured is None else {
                        "session_id": captured.id, "user_id": captured.user_id,
                        "user_traits": {**((profile.traits if profile else None) or {}),
                                        **{k: v for k, v in (captured.user_data or {}).items() if k != "user_id"}},
                        "metadata": captured.session_metadata or {}, "client_config": captured.client_config,
                        "started_at": iso(captured.started_at)}}

    # ---- Phase 2: accounts, organizations, scoped credentials ----

    @app.post("/api/auth/signup", status_code=201)
    def signup(body: SignupInput):
        try:
            email = normalize_email(body.email)
        except ValueError:
            raise HTTPException(422, "Invalid email")
        with sessions.begin() as session:
            if session.scalars(select(Account).where(Account.email == email)).first():
                raise HTTPException(409, "Account already exists")
            account = Account(id=str(uuid4()), email=email, password_hash=hash_password(body.password))
            session.add(account)
            session.flush()
            org = create_organization(session, body.name.strip() if body.name else f"{email} workspace")
            add_membership(session, org.id, account.id, "owner")
            ensure_plan(session, org.id)
            record, token = create_session(session, account.id, org.id)
            audit(session, org.id, "account.signup", account.id, account.id)
            return {"account": {"id": account.id, "email": email},
                    "organization": {"id": org.id, "name": org.name}, "session": token}

    @app.post("/api/auth/login")
    def login(body: LoginInput):
        try:
            email = normalize_email(body.email)
        except ValueError:
            raise HTTPException(401, "Invalid credentials")
        with sessions.begin() as session:
            account = session.scalars(select(Account).where(Account.email == email)).first()
            if account is None or not verify_password(body.password, account.password_hash):
                raise HTTPException(401, "Invalid credentials")
            membership = session.scalars(select(Membership).where(
                Membership.account_id == account.id).order_by(Membership.created_at)).first()
            record, token = create_session(session, account.id, membership.org_id if membership else None)
            return {"account": {"id": account.id, "email": account.email}, "session": token}

    @app.post("/api/auth/logout")
    def logout(request: Request):
        with sessions.begin() as session:
            resolved = require_session(request, session)
            resolved[0].revoked_at = utc_now()
            return {"ok": True}

    @app.get("/api/me")
    def me(request: Request):
        with sessions() as session:
            _, account = require_session(request, session)
            memberships = list(session.scalars(select(Membership).where(Membership.account_id == account.id)))
            orgs = []
            for membership in memberships:
                org = session.get(Organization, membership.org_id)
                if org:
                    orgs.append({"id": org.id, "name": org.name, "role": membership.role})
            return {"account": {"id": account.id, "email": account.email}, "organizations": orgs}

    @app.post("/api/orgs", status_code=201)
    def create_org(request: Request, body: OrgInput):
        name = body.name.strip()
        if not name:
            raise HTTPException(422, "name cannot be blank")
        with sessions.begin() as session:
            _, account = require_session(request, session)
            org = create_organization(session, name)
            add_membership(session, org.id, account.id, "owner")
            ensure_plan(session, org.id)
            audit(session, org.id, "org.create", org.id, account.id)
            return {"id": org.id, "name": org.name, "role": "owner"}

    @app.get("/api/orgs")
    def list_orgs(request: Request):
        with sessions() as session:
            _, account = require_session(request, session)
            out = []
            for membership in session.scalars(select(Membership).where(Membership.account_id == account.id)):
                org = session.get(Organization, membership.org_id)
                if org:
                    out.append({"id": org.id, "name": org.name, "role": membership.role})
            return out

    @app.post("/api/orgs/{id}/members", status_code=201)
    def add_member(request: Request, id: str, body: MemberInput):
        with sessions.begin() as session:
            _, account = require_session(request, session)
            membership = org_membership(session, id, account.id)
            from .auth import has_role as _has_role
            if not _has_role(membership.role, "admin"):
                raise HTTPException(403, "Admin role required")
            try:
                email = normalize_email(body.email)
            except ValueError:
                raise HTTPException(422, "Invalid email")
            target = session.scalars(select(Account).where(Account.email == email)).first()
            if target is None:
                raise HTTPException(404, "Account not found for email")
            existing = session.get(Membership, (id, target.id))
            if existing:
                existing.role = body.role
            else:
                add_membership(session, id, target.id, body.role)
            audit(session, id, "member.add", f"{target.id}:{body.role}", account.id)
            return {"org_id": id, "account_id": target.id, "role": body.role}

    @app.patch("/api/orgs/{id}/members/{account_id}")
    def update_member(request: Request, id: str, account_id: str, body: MemberPatch):
        from .auth import has_role as _has_role
        with sessions.begin() as session:
            _, account = require_session(request, session)
            membership = org_membership(session, id, account.id)
            if not _has_role(membership.role, "admin"):
                raise HTTPException(403, "Admin role required")
            target = session.get(Membership, (id, account_id))
            if target is None:
                raise HTTPException(404, "Membership not found")
            if target.role == "owner" and body.role != "owner":
                owners = session.execute(select(func.count()).select_from(Membership).where(
                    Membership.org_id == id, Membership.role == "owner")).scalar_one()
                if owners <= 1:
                    raise HTTPException(422, "Cannot remove the last owner")
            target.role = body.role
            audit(session, id, "member.update", f"{account_id}:{body.role}", account.id)
            return {"org_id": id, "account_id": account_id, "role": body.role}

    @app.delete("/api/orgs/{id}/members/{account_id}")
    def remove_member(request: Request, id: str, account_id: str):
        from .auth import has_role as _has_role
        with sessions.begin() as session:
            _, account = require_session(request, session)
            membership = org_membership(session, id, account.id)
            if not _has_role(membership.role, "admin"):
                raise HTTPException(403, "Admin role required")
            target = session.get(Membership, (id, account_id))
            if target is None:
                raise HTTPException(404, "Membership not found")
            if target.role == "owner":
                owners = session.execute(select(func.count()).select_from(Membership).where(
                    Membership.org_id == id, Membership.role == "owner")).scalar_one()
                if owners <= 1:
                    raise HTTPException(422, "Cannot remove the last owner")
            session.delete(target)
            audit(session, id, "member.remove", account_id, account.id)
            return {"ok": True}

    @app.post("/api/orgs/{id}/projects", status_code=201)
    def create_org_project(request: Request, id: str, body: OrgProjectInput):
        with sessions.begin() as session:
            _, account = require_session(request, session)
            org_membership(session, id, account.id)
            org_project_probe = Project(id="", org_id=id)
            try:
                require_project_role(session, org_project_probe, account.id, "admin")
            except PermissionError:
                raise HTTPException(403, "Admin role required")
            project = create_project(session, body.name.strip() or "project", org_id=id)
            env = ensure_environment(session, project.id, body.environment.strip() or "production")
            record, secret = mint_credential(session, project.id, env.id, "default", account.id)
            audit(session, id, "project.create", project.id, account.id)
            return {**project_dict(project), "environment": env.name,
                    "credential": {"id": record.id, "prefix": record.prefix, "secret": secret}}

    @app.get("/api/orgs/{id}/projects")
    def list_org_projects(request: Request, id: str):
        with sessions() as session:
            _, account = require_session(request, session)
            org_membership(session, id, account.id)
            return [project_dict(p) for p in session.scalars(
                select(Project).where(Project.org_id == id).order_by(Project.created_at, Project.id))]

    @app.post("/api/projects/{id}/credentials", status_code=201)
    def create_credential(request: Request, id: str, body: CredentialInput):
        with sessions.begin() as session:
            _, account = require_session(request, session)
            project = org_project(session, id, account.id, "admin")
            env = ensure_environment(session, project.id, (body.environment or "production").strip() or "production")
            record, secret = mint_credential(session, project.id, env.id, body.name, account.id)
            audit(session, project.org_id, "credential.create", record.id, account.id)
            return {"id": record.id, "prefix": record.prefix, "secret": secret,
                    "environment": env.name, "scope": "ingest"}

    @app.get("/api/projects/{id}/credentials")
    def list_credentials(request: Request, id: str):
        with sessions() as session:
            _, account = require_session(request, session)
            project = org_project(session, id, account.id, "admin")
            out = []
            for record in session.scalars(select(Credential).where(Credential.project_id == project.id)):
                env_name = None
                if record.environment_id:
                    env = session.get(Environment, record.environment_id)
                    env_name = env.name if env else None
                out.append({"id": record.id, "name": record.name, "prefix": record.prefix,
                            "scope": record.scope, "environment": env_name,
                            "revoked": record.revoked_at is not None,
                            "created_at": iso(record.created_at)})
            return out

    @app.post("/api/credentials/{id}/revoke")
    def revoke_credential(request: Request, id: str):
        with sessions.begin() as session:
            _, account = require_session(request, session)
            record = session.get(Credential, id)
            if record is None:
                raise HTTPException(404, "Credential not found")
            project = org_project(session, record.project_id, account.id, "admin")
            record.revoked_at = utc_now()
            audit(session, project.org_id, "credential.revoke", record.id, account.id)
            return {"ok": True}

    # ---- Phase 2: ingestion diagnostics, capture, usage, audit, retention ----

    @app.get("/api/jobs")
    def jobs(request: Request, project_id: str):
        with sessions() as session:
            _, account = require_session(request, session)
            project = org_project(session, project_id, account.id, "member")
            stats = queue_mod.job_stats(session, project.id)
            rows = list(session.scalars(select(IngestionJob).where(
                IngestionJob.project_id == project.id).order_by(
                IngestionJob.updated_at.desc()).limit(50)))
            return {**stats, "recent": [
                {"event_id": job.event_id, "state": job.state, "retry_count": job.retry_count,
                 "error_code": job.error_code, "mirror_state": job.mirror_state,
                 "mirror_attempts": job.mirror_attempts,
                 "updated_at": iso(job.updated_at)} for job in rows]}

    @app.post("/api/jobs/{project_id}/{event_id}/replay")
    def replay_job(request: Request, project_id: str, event_id: str):
        with sessions.begin() as session:
            _, account = require_session(request, session)
            project = org_project(session, project_id, account.id, "admin")
            job = session.get(IngestionJob, (project.id, event_id))
            if job is None:
                raise HTTPException(404, "Job not found")
            job.state, job.error_code, job.next_retry_at = "pending", None, None
            job.updated_at = utc_now()
            audit(session, project.org_id, "job.replay", f"{project.id}:{event_id}", account.id)
            if settings.inline_process:
                queue_mod.process_pending(session, engine, settings, project_id=project.id)
            return {"ok": True, "state": job.state}

    @app.patch("/api/projects/{id}/capture")
    def update_capture(request: Request, id: str, body: CaptureInput):
        with sessions.begin() as session:
            _, account = require_session(request, session)
            project = org_project(session, id, account.id, "admin")
            current = project_settings(project)
            if body.capture_content is not None:
                current["capture_content"] = body.capture_content
            if body.redact_keys is not None:
                current["redact_keys"] = [k for k in body.redact_keys if k][:50]
            if body.retention_days is not None:
                current["retention_days"] = body.retention_days
            if body.public_ingest is not None:
                current["public_ingest"] = body.public_ingest
            project.settings = current
            audit(session, project.org_id, "project.capture", project.id, account.id)
            return {"project_id": project.id, "settings": current}

    @app.get("/api/projects/{id}/usage")
    def project_usage(request: Request, id: str):
        with sessions() as session:
            _, account = require_session(request, session)
            project = org_project(session, id, account.id, "member")
            return {"project_id": project.id, **queue_mod.job_stats(session, project.id)}

    @app.get("/api/projects/{id}/setup")
    def project_setup(request: Request, id: str):
        """Connection/setup status for the investigation interface."""
        with sessions() as session:
            project = session.get(Project, id)
            if project is None:
                raise HTTPException(404, "Project not found")
            dashboard_access(request, session, project)
            legacy_key = bool(project.api_key)
            cred_count = session.execute(select(func.count()).select_from(Credential).where(
                Credential.project_id == project.id,
                Credential.revoked_at.is_(None))).scalar_one()
            event_count = session.execute(select(func.count()).select_from(Event).where(
                Event.project_id == project.id)).scalar_one()
            conv_count = session.execute(select(func.count(func.distinct(Event.conversation_id))).where(
                Event.project_id == project.id)).scalar_one()
            last = session.scalars(select(Event).where(Event.project_id == project.id).order_by(
                Event.timestamp.desc()).limit(1)).first()
            stats = queue_mod.job_stats(session, project.id)
            settings_summary = project_settings(project)
            return {
                "project": project_dict(project),
                "key_configured": bool(legacy_key or cred_count),
                "active_credentials": cred_count,
                "events_received": event_count,
                "conversations": conv_count,
                "last_event_at": iso(last.timestamp) if last else None,
                "jobs": stats["jobs"],
                "usage_events": stats["usage_events"],
                "capture": {"capture_content": settings_summary.get("capture_content", True),
                            "retention_days": settings_summary.get("retention_days", 90)},
            }

    @app.get("/api/orgs/{id}/audit")
    def org_audit(request: Request, id: str, limit: int = Query(default=50, ge=1, le=200)):
        with sessions() as session:
            _, account = require_session(request, session)
            membership = org_membership(session, id, account.id)
            from .auth import has_role as _has_role
            if not _has_role(membership.role, "admin"):
                raise HTTPException(403, "Admin role required")
            rows = list(session.scalars(select(AuditRecord).where(
                AuditRecord.org_id == id).order_by(AuditRecord.created_at.desc()).limit(limit)))
            return [{"id": row.id, "action": row.action, "resource": row.resource,
                     "account_id": row.account_id, "created_at": iso(row.created_at)} for row in rows]

    @app.post("/api/projects/{id}/retention/run")
    def run_retention_now(request: Request, id: str):
        with sessions.begin() as session:
            _, account = require_session(request, session)
            project = org_project(session, id, account.id, "admin")
            result = queue_mod.run_retention(session, engine, project)
            audit(session, project.org_id, "project.retention", project.id, account.id)
            return {"project_id": project.id, **result}

    # ---- Phase 5: behavior rules ----

    def rule_dict(rule):
        return {"id": rule.id, "project_id": rule.project_id, "name": rule.name, "kind": rule.kind,
                "pattern": rule.pattern, "tool": rule.tool, "severity": rule.severity,
                "enabled": rule.enabled, "version": rule.version,
                "created_at": iso(rule.created_at)}

    @app.get("/api/projects/{id}/rules")
    def list_rules(request: Request, id: str):
        with sessions() as session:
            project = session.get(Project, id)
            if project is None:
                raise HTTPException(404, "Project not found")
            dashboard_access(request, session, project)
            resolved = session_auth(request, session)
            if project.org_id is not None and resolved is not None:
                try:
                    require_project_role(session, project, resolved[1].id, "viewer")
                except PermissionError:
                    raise HTTPException(403, "Insufficient role")
            return [rule_dict(r) for r in session.scalars(
                select(BehaviorRule).where(BehaviorRule.project_id == project.id)
                .order_by(BehaviorRule.created_at))]

    @app.post("/api/projects/{id}/rules", status_code=201)
    def create_rule(request: Request, id: str, body: RuleInput):
        import re as re_module
        if body.kind == "forbidden_phrase":
            if not (body.pattern or "").strip():
                raise HTTPException(422, "pattern is required for forbidden_phrase")
            try:
                re_module.compile(body.pattern)
            except re_module.error:
                raise HTTPException(422, "pattern is not a valid regex")
        if body.kind == "required_tool" and not (body.tool or "").strip():
            raise HTTPException(422, "tool is required for required_tool")
        with sessions.begin() as session:
            project = session.get(Project, id)
            if project is None or (project.org_id is None and session_auth(request, session)):
                raise HTTPException(404, "Project not found")
            account_id = None
            if project.org_id is not None:
                _, account = require_session(request, session)
                org_project(session, project.id, account.id, "admin")
                account_id = account.id
            rule = BehaviorRule(id=str(uuid4()), project_id=project.id, name=body.name,
                                kind=body.kind, pattern=body.pattern, tool=body.tool,
                                severity=body.severity, enabled=True, version="1",
                                created_by=account_id)
            session.add(rule)
            session.flush()
            if project.org_id is not None:
                audit(session, project.org_id, "rule.create", rule.id, account_id)
            return rule_dict(rule)

    @app.patch("/api/rules/{id}")
    def update_rule(request: Request, id: str, body: RulePatch):
        with sessions.begin() as session:
            rule = session.get(BehaviorRule, id)
            if rule is None:
                raise HTTPException(404, "Rule not found")
            project = session.get(Project, rule.project_id)
            account_id = None
            if project is not None and project.org_id is not None:
                _, account = require_session(request, session)
                org_project(session, project.id, account.id, "admin")
                account_id = account.id
            if body.enabled is not None:
                rule.enabled = body.enabled
            if body.severity is not None:
                rule.severity = body.severity
            if project is not None and project.org_id is not None:
                audit(session, project.org_id, "rule.update", rule.id, account_id)
            return rule_dict(rule)

    @app.delete("/api/rules/{id}")
    def delete_rule(request: Request, id: str):
        with sessions.begin() as session:
            rule = session.get(BehaviorRule, id)
            if rule is None:
                raise HTTPException(404, "Rule not found")
            project = session.get(Project, rule.project_id)
            if project is not None and project.org_id is not None:
                _, account = require_session(request, session)
                org_project(session, project.id, account.id, "admin")
                audit(session, project.org_id, "rule.delete", rule.id, account.id)
            session.delete(rule)
            return {"ok": True}

    # ---- Phase 6: intents ----

    def intent_dict(intent):
        return {"id": intent.id, "project_id": intent.project_id, "name": intent.name,
                "description": intent.description, "examples": intent.examples,
                "enabled": intent.enabled, "version": intent.version,
                "created_at": iso(intent.created_at)}

    def intent_project(request, db_session, project_id, minimum):
        project = db_session.get(Project, project_id)
        if project is None:
            raise HTTPException(404, "Project not found")
        dashboard_access(request, db_session, project)
        resolved = session_auth(request, db_session)
        if project.org_id is not None and resolved is not None:
            try:
                require_project_role(db_session, project, resolved[1].id, minimum)
            except PermissionError:
                raise HTTPException(403, "Insufficient role")
        elif project.org_id is not None and minimum == "admin":
            # Org projects require a session for mutations.
            raise HTTPException(401, "Login required")
        return project

    @app.get("/api/projects/{id}/intents")
    def list_intents(request: Request, id: str):
        with sessions() as session:
            intent_project(request, session, id, "viewer")
            return [intent_dict(r) for r in session.scalars(
                select(Intent).where(Intent.project_id == id).order_by(Intent.created_at))]

    @app.post("/api/projects/{id}/intents", status_code=201)
    def create_intent(request: Request, id: str, body: IntentInput):
        with sessions.begin() as session:
            project = intent_project(request, session, id, "admin")
            account_id = None
            resolved = session_auth(request, session)
            if resolved is not None:
                account_id = resolved[1].id
            intent = Intent(id=str(uuid4()), project_id=project.id, name=body.name,
                            description=body.description, examples=body.examples,
                            enabled=True, version="1", created_by=account_id)
            session.add(intent)
            session.flush()
            if project.org_id is not None:
                audit(session, project.org_id, "intent.create", intent.id, account_id)
            return intent_dict(intent)

    @app.patch("/api/intents/{id}")
    def update_intent(request: Request, id: str, body: IntentPatch):
        with sessions.begin() as session:
            intent = session.get(Intent, id)
            if intent is None:
                raise HTTPException(404, "Intent not found")
            project = intent_project(request, session, intent.project_id, "admin")
            if body.enabled is not None:
                intent.enabled = body.enabled
            if body.description is not None:
                intent.description = body.description
            resolved = session_auth(request, session)
            if project.org_id is not None:
                audit(session, project.org_id, "intent.update", intent.id,
                      resolved[1].id if resolved else None)
            return intent_dict(intent)

    @app.delete("/api/intents/{id}")
    def delete_intent(request: Request, id: str):
        with sessions.begin() as session:
            intent = session.get(Intent, id)
            if intent is None:
                raise HTTPException(404, "Intent not found")
            project = intent_project(request, session, intent.project_id, "admin")
            resolved = session_auth(request, session)
            if project.org_id is not None:
                audit(session, project.org_id, "intent.delete", intent.id,
                      resolved[1].id if resolved else None)
            session.delete(intent)
            return {"ok": True}

    insights_mod.register(
        app, sessions=sessions,
        read_project=lambda request, db_session, project_id: intent_project(request, db_session, project_id, "viewer"),
        project_signals=lambda db_session, project_id: project_analysis(db_session, project_id)[:2])

    # ---- Phase 6: discovery ----

    def discovery_project(request, db_session, project_id, minimum):
        project = db_session.get(Project, project_id)
        if project is None:
            raise HTTPException(404, "Project not found")
        dashboard_access(request, db_session, project)
        resolved = session_auth(request, db_session)
        if project.org_id is not None and resolved is not None:
            try:
                require_project_role(db_session, project, resolved[1].id, minimum)
            except PermissionError:
                raise HTTPException(403, "Insufficient role")
        elif project.org_id is not None and minimum == "admin":
            raise HTTPException(401, "Login required")
        return project

    def discovery_conversations(db_session, project_id, start, end):
        events = list(db_session.scalars(select(Event).where(
            Event.project_id == project_id).order_by(Event.timestamp, Event.id)))
        by_conv = {}
        for event in events:
            if start <= utc(event.timestamp) <= end:
                by_conv.setdefault(event.conversation_id, []).append(event)
        return events, by_conv

    def sync_discovery(db_session, project, groups):
        """Upsert computed groups; refresh their memberships. Edit rows win."""
        from .db import SemanticCluster as ClusterModel, SemanticMembership as MembershipModel
        for group in groups:
            row = db_session.scalars(select(ClusterModel).where(
                ClusterModel.project_id == project.id,
                ClusterModel.key == group["key"])).first()
            if row is None:
                row = ClusterModel(id=str(uuid4()), project_id=project.id, key=group["key"],
                                   label=group["label"], status="open",
                                   member_count=group["count"], updated_at=utc_now())
                db_session.add(row)
                db_session.flush()
            else:
                row.member_count = group["count"]
                row.updated_at = utc_now()
                if not row.label_override:
                    row.label = group["label"]
            db_session.execute(delete(SemanticMembership).where(
                SemanticMembership.cluster_id == row.id))
            for member in group["member_ids"]:
                db_session.add(SemanticMembership(cluster_id=row.id, conversation_id=member,
                                                  score=1.0))
        db_session.flush()

    @app.get("/api/projects/{id}/discovery")
    def get_discovery(request: Request, id: str, range: Range = "7d"):
        from . import clustering as clustering_mod
        with sessions() as session:
            project = session.get(Project, id)
            if project is None:
                raise HTTPException(404, "Project not found")
            dashboard_access(request, session, project)
            start, end = window(range)
            _, by_conv = discovery_conversations(session, project.id, start, end)
            units, users = [], set()
            for conv_id, messages in by_conv.items():
                text = " | ".join(m.content for m in messages if (m.content or "").strip())[:2000]
                if messages[0].user_id:
                    users.add(messages[0].user_id)
                for m in messages:
                    if m.user_id:
                        users.add(m.user_id)
                if text.strip():
                    units.append({"id": conv_id, "text": text})
            intents = [{"id": r.id, "name": r.name, "examples": r.examples, "enabled": r.enabled}
                       for r in session.scalars(select(Intent).where(
                           Intent.project_id == project.id, Intent.enabled == True))]  # noqa: E712
            intent_hits = {}
            for unit in units:
                match = clustering_mod.match_intent(unit["text"], intents)
                if match:
                    intent_hits[unit["id"]] = match
            groups = clustering_mod.discover(units)
            sync_discovery(session, project, groups)
            session.commit()
            hidden = {r.key: r for r in session.scalars(select(SemanticCluster).where(
                SemanticCluster.project_id == project.id,
                SemanticCluster.status.in_(("dismissed", "merged", "split"))))}
            rows = {r.key: r for r in session.scalars(select(SemanticCluster).where(
                SemanticCluster.project_id == project.id))}
            clusters = []
            for group in groups:
                if group["key"] in hidden:
                    continue
                row = rows.get(group["key"])
                members = [{"conversation_id": m} for m in group["member_ids"]]
                clusters.append({
                    "id": row.id if row else group["key"], "key": group["key"],
                    "label": (row.label_override or row.label) if row and (row.label_override or row.label) else group["label"],
                    "status": row.status if row else "open",
                    "count": group["count"],
                    "affected_users": len({m.user_id for _, ms in by_conv.items() for m in ms
                                           if m.conversation_id in group["member_ids"] and m.user_id}),
                    "evidence": [{"conversation_id": group["representative_id"],
                                  "excerpt": group["representative_text"],
                                  "reason": f"Representative of {group['count']} grouped conversations"}],
                    "members": [m for m in group["member_ids"]],
                    "detector_version": clustering_mod.DISCOVERY_VERSION,
                })
            manual = []
            for row in session.scalars(select(SemanticCluster).where(
                    SemanticCluster.project_id == project.id, SemanticCluster.status == "open")):
                if row.key.startswith("m") and len(row.key) == 16:
                    members = [m.conversation_id for m in session.scalars(
                        select(SemanticMembership).where(SemanticMembership.cluster_id == row.id))]
                    manual.append({"id": row.id, "key": row.key,
                                   "label": row.label_override or row.label, "status": row.status,
                                   "count": len(members), "affected_users": 0,
                                   "evidence": [], "members": members,
                                   "detector_version": clustering_mod.DISCOVERY_VERSION})
            intent_summary = []
            for intent in intents:
                matched = [cid for cid, hit in intent_hits.items() if hit["intent_id"] == intent["id"]]
                intent_summary.append({"intent_id": intent["id"], "intent_name": intent["name"],
                                       "conversations": len(matched), "sample": matched[:5]})
            total_messages = sum(len(ms) for ms in by_conv.values())
            clustered = {m for c in clusters for m in c["members"]}
            return {
                "project": project_dict(project),
                "clusters": clusters + manual,
                "intents": intent_summary,
                "coverage": {
                    "conversations_total": len(by_conv),
                    "conversations_analyzed": len(units),
                    "messages_total": total_messages,
                    "users_total": len(users),
                    "clustered": len(clustered),
                    "unassigned": len(units) - len(clustered),
                },
            }

    @app.patch("/api/discovery/{cluster_id}")
    def update_discovery(request: Request, cluster_id: str, body: DiscoveryStatus):
        """Dismiss hides the group. Evidence stays in retained telemetry."""
        with sessions.begin() as session:
            row = session.get(SemanticCluster, cluster_id)
            if row is None:
                raise HTTPException(404, "Cluster not found")
            project = discovery_project(request, session, row.project_id, "member")
            row.status = body.status
            row.updated_at = utc_now()
            resolved = session_auth(request, session)
            if project.org_id is not None:
                audit(session, project.org_id, "discovery.update", row.id,
                      resolved[1].id if resolved else None)
            return {"id": row.id, "status": row.status}

    @app.post("/api/discovery/{cluster_id}/rename")
    def rename_discovery(request: Request, cluster_id: str, body: DiscoveryRename):
        with sessions.begin() as session:
            row = session.get(SemanticCluster, cluster_id)
            if row is None:
                raise HTTPException(404, "Cluster not found")
            project = discovery_project(request, session, row.project_id, "member")
            row.label_override = body.label.strip()
            row.updated_at = utc_now()
            resolved = session_auth(request, session)
            if project.org_id is not None:
                audit(session, project.org_id, "discovery.rename", row.id,
                      resolved[1].id if resolved else None)
            return {"id": row.id, "label": row.label_override}

    def discovery_manual(db_session, project, label, member_ids, account_id):
        existing = {e.conversation_id for e in db_session.scalars(select(Event).where(
            Event.project_id == project.id))}
        unknown = [m for m in dict.fromkeys(member_ids) if m not in existing]
        if unknown:
            raise HTTPException(422, f"Unknown conversations: {unknown[:5]}")
        members = [m for m in dict.fromkeys(member_ids) if m in existing]
        key = "m" + str(uuid4()).replace("-", "")[:15]
        row = SemanticCluster(id=str(uuid4()), project_id=project.id, key=key,
                              label=label.strip()[:200], status="open",
                              member_count=len(members), updated_at=utc_now())
        db_session.add(row)
        db_session.flush()
        for member in members:
            db_session.add(SemanticMembership(cluster_id=row.id, conversation_id=member, score=1.0))
        return row

    @app.post("/api/projects/{id}/discovery/manual", status_code=201)
    def manual_discovery(request: Request, id: str, body: DiscoveryMembers):
        with sessions.begin() as session:
            project = discovery_project(request, session, id, "admin")
            resolved = session_auth(request, session)
            account_id = resolved[1].id if resolved else None
            row = discovery_manual(session, project, body.label, body.member_conversation_ids, account_id)
            if project.org_id is not None:
                audit(session, project.org_id, "discovery.create", row.id, account_id)
            return {"id": row.id, "key": row.key, "label": row.label,
                    "members": body.member_conversation_ids}

    @app.post("/api/projects/{id}/discovery/merge", status_code=201)
    def merge_discovery(request: Request, id: str, body: DiscoveryMerge):
        with sessions.begin() as session:
            project = discovery_project(request, session, id, "admin")
            resolved = session_auth(request, session)
            account_id = resolved[1].id if resolved else None
            sources = [session.get(SemanticCluster, source_id) for source_id in body.source_ids]
            if any(r is None or r.project_id != project.id or r.status != "open" for r in sources):
                raise HTTPException(404, "Source cluster not found")
            members = []
            for row in sources:
                members.extend(m.conversation_id for m in session.scalars(
                    select(SemanticMembership).where(SemanticMembership.cluster_id == row.id)))
            row = discovery_manual(session, project, body.label, members, account_id)
            for source in sources:
                source.status = "merged"
                source.merged_into = row.id
                source.updated_at = utc_now()
            if project.org_id is not None:
                audit(session, project.org_id, "discovery.merge", row.id, account_id)
            return {"id": row.id, "label": row.label, "members": members}

    @app.post("/api/projects/{id}/discovery/split", status_code=201)
    def split_discovery(request: Request, id: str, body: DiscoveryMembers):
        with sessions.begin() as session:
            project = discovery_project(request, session, id, "admin")
            resolved = session_auth(request, session)
            account_id = resolved[1].id if resolved else None
            current = session.scalars(select(SemanticCluster).where(
                SemanticCluster.project_id == project.id,
                SemanticCluster.status == "open")).all()
            if not current:
                raise HTTPException(404, "No open clusters to split")
            # Split reads live membership so evidence never goes stale.
            by_member = {}
            for row in current:
                for m in session.scalars(select(SemanticMembership).where(
                        SemanticMembership.cluster_id == row.id)):
                    by_member.setdefault(m.conversation_id, []).append(row)
            subset = [m for m in dict.fromkeys(body.member_conversation_ids) if m in by_member]
            if len(subset) < 1:
                raise HTTPException(422, "Split needs clustered members")
            touched = set()
            for member in subset:
                for row in by_member.get(member, []):
                    touched.add(row.id)
            remainder = []
            for row in current:
                if row.id not in touched:
                    continue
                for m in session.scalars(select(SemanticMembership).where(
                        SemanticMembership.cluster_id == row.id)):
                    if m.conversation_id not in subset:
                        remainder.append(m.conversation_id)
            remainder = list(dict.fromkeys(remainder))
            if not remainder:
                raise HTTPException(422, "Split would leave nothing behind")
            first = discovery_manual(session, project, body.label, subset, account_id)
            kept = discovery_manual(session, project, "Split remainder", remainder, account_id)
            for row in current:
                if row.id in touched:
                    row.status = "split"
                    row.updated_at = utc_now()
            if project.org_id is not None:
                audit(session, project.org_id, "discovery.split", first.id, account_id)
            return {"id": first.id, "label": first.label,
                    "members": subset, "remainder_id": kept.id}

    # ---- Phase 7: alerts, billing, export, ops ----

    @app.get("/api/projects/{id}/alerts")
    def list_alerts(request: Request, id: str):
        with sessions() as session:
            project = session.get(Project, id)
            if project is None:
                raise HTTPException(404, "Project not found")
            dashboard_access(request, session, project)
            return [alerts_mod.public_rule(r) for r in session.scalars(
                select(AlertRule).where(AlertRule.project_id == project.id)
                .order_by(AlertRule.created_at))]

    @app.post("/api/projects/{id}/alerts", status_code=201)
    def create_alert(request: Request, id: str, body: AlertRuleInput):
        with sessions.begin() as session:
            project = session.get(Project, id)
            if project is None:
                raise HTTPException(404, "Project not found")
            dashboard_access(request, session, project)
            account_id = None
            if project.org_id is not None:
                _, account = require_session(request, session)
                org_project(session, project.id, account.id, "admin")
                account_id = account.id
            rule = AlertRule(id=str(uuid4()), project_id=project.id, name=body.name.strip(),
                             kind=body.kind, signal_kind=body.signal_kind,
                             threshold=body.threshold, window_hours=body.window_hours,
                             min_samples=body.min_samples, cooldown_hours=body.cooldown_hours,
                             channels=[c.model_dump() for c in body.channels],
                             enabled=True, state="ok", created_by=account_id)
            session.add(rule)
            session.flush()
            if project.org_id is not None:
                audit(session, project.org_id, "alert.create", rule.id, account_id)
            return alerts_mod.public_rule(rule)

    @app.patch("/api/alerts/{id}")
    def update_alert(request: Request, id: str, body: AlertRulePatch):
        with sessions.begin() as session:
            rule = session.get(AlertRule, id)
            if rule is None:
                raise HTTPException(404, "Alert not found")
            project = session.get(Project, rule.project_id)
            if project is not None and project.org_id is not None:
                _, account = require_session(request, session)
                org_project(session, project.id, account.id, "admin")
                audit(session, project.org_id, "alert.update", rule.id, account.id)
            if body.enabled is not None:
                rule.enabled = body.enabled
            if body.threshold is not None:
                rule.threshold = body.threshold
            if body.cooldown_hours is not None:
                rule.cooldown_hours = body.cooldown_hours
            return alerts_mod.public_rule(rule)

    @app.delete("/api/alerts/{id}")
    def delete_alert(request: Request, id: str):
        with sessions.begin() as session:
            rule = session.get(AlertRule, id)
            if rule is None:
                raise HTTPException(404, "Alert not found")
            project = session.get(Project, rule.project_id)
            if project is not None and project.org_id is not None:
                _, account = require_session(request, session)
                org_project(session, project.id, account.id, "admin")
                audit(session, project.org_id, "alert.delete", rule.id, account.id)
            session.execute(delete(AlertDelivery).where(AlertDelivery.rule_id == rule.id))
            session.delete(rule)
            return {"ok": True}

    @app.post("/api/projects/{id}/alerts/evaluate")
    def evaluate_alerts(request: Request, id: str):
        with sessions.begin() as session:
            project = session.get(Project, id)
            if project is None:
                raise HTTPException(404, "Project not found")
            dashboard_access(request, session, project)
            if project.org_id is not None:
                _, account = require_session(request, session)
                org_project(session, project.id, account.id, "admin")
            results = []
            for rule in session.scalars(select(AlertRule).where(
                    AlertRule.project_id == project.id, AlertRule.enabled == True)):  # noqa: E712
                fired, detail = alerts_mod.evaluate_rule(session, rule)
                results.append({"rule_id": rule.id, "fired": fired, "detail": detail})
            return {"evaluated": len(results), "results": results}

    @app.get("/api/projects/{id}/deliveries")
    def list_deliveries(request: Request, id: str, limit: int = Query(default=50, ge=1, le=200)):
        with sessions() as session:
            project = session.get(Project, id)
            if project is None:
                raise HTTPException(404, "Project not found")
            dashboard_access(request, session, project)
            rows = list(session.scalars(select(AlertDelivery).where(
                AlertDelivery.project_id == project.id)
                .order_by(AlertDelivery.created_at.desc()).limit(limit)))
            return [alerts_mod.public_delivery(d) for d in rows]

    @app.post("/api/deliveries/{id}/replay")
    def replay_delivery(request: Request, id: str):
        with sessions.begin() as session:
            delivery = session.get(AlertDelivery, id)
            if delivery is None:
                raise HTTPException(404, "Delivery not found")
            project = session.get(Project, delivery.project_id)
            if project is not None and project.org_id is not None:
                _, account = require_session(request, session)
                org_project(session, project.id, account.id, "admin")
                audit(session, project.org_id, "delivery.replay", delivery.id, account.id)
            delivery.state = "queued"
            delivery.error_code = None
            delivery.next_retry_at = utc_now()
            return {"ok": True}

    @app.get("/api/orgs/{id}/billing")
    def org_billing(request: Request, id: str):
        with sessions() as session:
            _, account = require_session(request, session)
            membership = org_membership(session, id, account.id)
            from .auth import has_role as _has_role
            if not _has_role(membership.role, "admin"):
                raise HTTPException(403, "Admin role required")
            plan = ensure_plan(session, id)
            used = month_usage(session, id)
            return {"org_id": id, "plan": plan.name,
                    "monthly_event_limit": plan.monthly_event_limit,
                    "used_this_month": used,
                    "percent": round(100 * used / plan.monthly_event_limit, 2)
                    if plan.monthly_event_limit else 0}

    @app.get("/api/projects/{id}/export")
    def export_project(request: Request, id: str, range: Range = "7d", limit: int = Query(default=1000, ge=1, le=5000)):
        with sessions() as session:
            project = session.get(Project, id)
            if project is None:
                raise HTTPException(404, "Project not found")
            dashboard_access(request, session, project)
            account_id = None
            if project.org_id is not None:
                _, account = require_session(request, session)
                org_project(session, project.id, account.id, "member")
                account_id = account.id
            start, end = window(range)
            rows = list(session.scalars(select(Event).where(
                Event.project_id == project.id).order_by(Event.timestamp, Event.id).limit(limit + 1)))
            in_range = [e for e in rows if start <= utc(e.timestamp) <= end][:limit]
            if project.org_id is not None:
                with sessions.begin() as audit_session:
                    audit(audit_session, project.org_id, "project.export", project.id, account_id)
            return {"project_id": project.id, "truncated": len(rows) > limit,
                    "events": [analysis.event_dict(e) for e in in_range]}

    @app.delete("/api/projects/{id}")
    def delete_project(request: Request, id: str):
        with sessions.begin() as session:
            project = session.get(Project, id)
            if project is None:
                raise HTTPException(404, "Project not found")
            dashboard_access(request, session, project)
            account_id = None
            if project.org_id is not None:
                _, account = require_session(request, session)
                org_project(session, project.id, account.id, "admin")
                account_id = account.id
                audit(session, project.org_id, "project.delete", project.id, account_id)
            for row in session.scalars(select(AlertRule).where(AlertRule.project_id == project.id)):
                session.execute(delete(AlertDelivery).where(AlertDelivery.rule_id == row.id))
            session.execute(delete(AlertDelivery).where(AlertDelivery.project_id == project.id))
            session.execute(delete(AlertRule).where(AlertRule.project_id == project.id))
            session.execute(delete(BehaviorRule).where(BehaviorRule.project_id == project.id))
            session.execute(delete(Intent).where(Intent.project_id == project.id))
            for row in session.scalars(select(SemanticCluster).where(
                    SemanticCluster.project_id == project.id)):
                session.execute(delete(SemanticMembership).where(
                    SemanticMembership.cluster_id == row.id))
            session.execute(delete(SemanticCluster).where(SemanticCluster.project_id == project.id))
            session.execute(delete(ClusterState).where(ClusterState.project_id == project.id))
            session.execute(delete(Event).where(Event.project_id == project.id))
            session.execute(delete(UsageRecord).where(UsageRecord.project_id == project.id))
            session.execute(delete(IngestionJob).where(IngestionJob.project_id == project.id))
            session.execute(delete(PayloadObject).where(PayloadObject.project_id == project.id))
            session.execute(delete(Credential).where(Credential.project_id == project.id))
            session.execute(delete(Environment).where(Environment.project_id == project.id))
            session.delete(project)
            return {"ok": True}

    def ops_scope(request, db_session):
        resolved = session_auth(request, db_session)
        if resolved is None:
            return None, "instance"
        _, account = resolved
        org_ids = [m.org_id for m in db_session.scalars(
            select(Membership).where(Membership.account_id == account.id))]
        project_ids = list(db_session.scalars(select(Project.id).where(
            Project.org_id.in_(org_ids)))) if org_ids else []
        return project_ids, "organization"

    @app.get("/api/ops/summary")
    def ops_summary(request: Request):
        from . import analysis as analysis_mod
        with sessions() as session:
            project_ids, _ = ops_scope(request, session)
            jobs = select(IngestionJob.state, func.count()).group_by(IngestionJob.state)
            if project_ids is not None:
                jobs = jobs.where(IngestionJob.project_id.in_(project_ids))
            backlog = {state: 0 for state in ("pending", "processed", "failed", "dead", "expired")}
            for state, count in session.execute(jobs).all():
                backlog[state] = count
            pending_oldest = None
            pending_query = select(func.min(IngestionJob.created_at)).where(
                IngestionJob.state.in_(("pending", "failed")))
            if project_ids is not None:
                pending_query = pending_query.where(IngestionJob.project_id.in_(project_ids))
            oldest = session.execute(pending_query).scalar_one_or_none()
            if oldest is not None:
                pending_oldest = max(0, int((utc_now() - utc(oldest)).total_seconds()))
            day_ago = utc_now() - timedelta(hours=24)
            deliveries = select(AlertDelivery.state, func.count()).where(
                AlertDelivery.created_at >= day_ago).group_by(AlertDelivery.state)
            if project_ids is not None:
                deliveries = deliveries.where(AlertDelivery.project_id.in_(project_ids))
            states = {state: count for state, count in session.execute(deliveries).all()}
            sent, failed = states.get("sent", 0), states.get("failed", 0) + states.get("sending", 0)
            events = select(Event).where(Event.timestamp >= day_ago)
            if project_ids is not None:
                events = events.where(Event.project_id.in_(project_ids))
            recent = list(session.scalars(events))
            convs = {e.conversation_id for e in recent}
            analyzed = {e.conversation_id for e in recent if (e.content or "").strip()}
            return {
                "queue": {"backlog": backlog, "oldest_pending_seconds": pending_oldest},
                "deliveries_24h": {"sent": sent, "failed": failed,
                                   "success_rate": round(100 * sent / (sent + failed), 1)
                                   if sent + failed else 100.0},
                "analysis_coverage_24h": {
                    "conversations_total": len(convs), "conversations_analyzed": len(analyzed),
                    "messages_total": len(recent),
                    "users_total": len({e.user_id for e in recent if e.user_id})},
            }

    # ---- Phase 8: evaluations and replay ----

    def dataset_dict(dataset):
        return {"id": dataset.id, "project_id": dataset.project_id, "name": dataset.name,
                "version": dataset.version, "status": dataset.status,
                "cases": dataset.cases, "case_count": len(dataset.cases or []),
                "created_at": iso(dataset.created_at)}

    def run_dict(run):
        return {"id": run.id, "dataset_id": run.dataset_id, "project_id": run.project_id,
                "baseline": run.baseline, "candidate": run.candidate,
                "repeats": run.repeats, "state": run.state, "results": run.results,
                "created_at": iso(run.created_at)}

    @app.get("/api/projects/{id}/datasets")
    def list_datasets(request: Request, id: str):
        with sessions() as session:
            project = session.get(Project, id)
            if project is None:
                raise HTTPException(404, "Project not found")
            dashboard_access(request, session, project)
            return [dataset_dict(d) for d in session.scalars(
                select(EvalDataset).where(EvalDataset.project_id == project.id)
                .order_by(EvalDataset.created_at))]

    @app.post("/api/projects/{id}/datasets", status_code=201)
    def create_dataset(request: Request, id: str, body: EvalDatasetInput):
        with sessions.begin() as session:
            project = session.get(Project, id)
            if project is None:
                raise HTTPException(404, "Project not found")
            dashboard_access(request, session, project)
            account_id = None
            if project.org_id is not None:
                _, account = require_session(request, session)
                org_project(session, project.id, account.id, "admin")
                account_id = account.id
            dataset = EvalDataset(id=str(uuid4()), project_id=project.id, name=body.name.strip(),
                                  version="1", status="draft",
                                  cases=[c.model_dump() for c in body.cases], created_by=account_id)
            session.add(dataset)
            session.flush()
            if project.org_id is not None:
                audit(session, project.org_id, "dataset.create", dataset.id, account_id)
            return dataset_dict(dataset)

    @app.post("/api/projects/{id}/datasets/from-findings", status_code=201)
    def dataset_from_findings(request: Request, id: str, body: FindingsDatasetInput):
        """Build reviewable cases from production signals plus healthy controls."""
        with sessions.begin() as session:
            project = session.get(Project, id)
            if project is None:
                raise HTTPException(404, "Project not found")
            dashboard_access(request, session, project)
            account_id = None
            if project.org_id is not None:
                _, account = require_session(request, session)
                org_project(session, project.id, account.id, "admin")
                account_id = account.id
            events = list(session.scalars(select(Event).where(
                Event.project_id == project.id).order_by(Event.timestamp, Event.id)))
            signals = analysis.analyze(events)
            by_conv = {}
            for event in events:
                by_conv.setdefault(event.conversation_id, []).append(event)
            cases = []
            for signal in signals:
                if signal["kind"] not in body.signal_kinds:
                    continue
                if len(cases) >= body.limit:
                    break
                messages = by_conv.get(signal["conversation_id"], [])
                user_text = next((m.content for m in messages if m.role == "user"), "")
                tools = [{"name": m.name or "tool", "recorded_output": m.content}
                         for m in messages if m.role == "tool" and m.span_id][:5]
                cases.append({"id": f"finding-{signal['event_id']}", "input": user_text,
                              "tools": tools,
                              "expected": {"tools_called": [t["name"] for t in tools],
                                           "no_violations": [signal["kind"]]}})
            if body.include_controls:
                healthy = [cid for cid, ms in by_conv.items()
                           if not any(s["conversation_id"] == cid for s in signals)][:body.limit]
                for cid in healthy:
                    if len(cases) >= body.limit:
                        break
                    messages = by_conv[cid]
                    user_text = next((m.content for m in messages if m.role == "user"), "")
                    recorded = [{"name": m.name or "tool", "recorded_output": m.content}
                                for m in messages if m.role == "tool" and m.span_id][:5]
                    cases.append({"id": f"control-{cid[:8]}", "input": user_text,
                                  "tools": recorded,
                                  "expected": {"no_violations": body.signal_kinds}})
            if not cases:
                raise HTTPException(422, "No matching findings or controls in this project")
            dataset = EvalDataset(id=str(uuid4()), project_id=project.id, name=body.name.strip(),
                                  version="1", status="draft", cases=cases, created_by=account_id)
            session.add(dataset)
            session.flush()
            if project.org_id is not None:
                audit(session, project.org_id, "dataset.create", dataset.id, account_id)
            return dataset_dict(dataset)

    @app.patch("/api/datasets/{id}")
    def update_dataset(request: Request, id: str, body: EvalDatasetPatch):
        with sessions.begin() as session:
            dataset = session.get(EvalDataset, id)
            if dataset is None:
                raise HTTPException(404, "Dataset not found")
            project = session.get(Project, dataset.project_id)
            if project is not None and project.org_id is not None:
                _, account = require_session(request, session)
                org_project(session, project.id, account.id, "admin")
                audit(session, project.org_id, "dataset.review", dataset.id, account.id)
            if body.status == "draft" and dataset.status != "draft":
                raise HTTPException(422, "Reviewed datasets stay reviewed")
            dataset.status = body.status
            return dataset_dict(dataset)

    @app.delete("/api/datasets/{id}")
    def delete_dataset(request: Request, id: str):
        with sessions.begin() as session:
            dataset = session.get(EvalDataset, id)
            if dataset is None:
                raise HTTPException(404, "Dataset not found")
            project = session.get(Project, dataset.project_id)
            if project is not None and project.org_id is not None:
                _, account = require_session(request, session)
                org_project(session, project.id, account.id, "admin")
                audit(session, project.org_id, "dataset.delete", dataset.id, account.id)
            session.execute(delete(EvalRun).where(EvalRun.dataset_id == dataset.id))
            session.delete(dataset)
            return {"ok": True}

    @app.post("/api/datasets/{id}/runs", status_code=201)
    def create_run(request: Request, id: str, body: EvalRunInput):
        with sessions.begin() as session:
            dataset = session.get(EvalDataset, id)
            if dataset is None:
                raise HTTPException(404, "Dataset not found")
            project = session.get(Project, dataset.project_id)
            if project is not None and project.org_id is not None:
                _, account = require_session(request, session)
                org_project(session, project.id, account.id, "admin")
                account_id = account.id
            else:
                account_id = None
            if dataset.status == "draft":
                raise HTTPException(422, "Review the dataset before running it")
            results = evaluate_mod.run_dataset(
                dataset.project_id, dataset.cases or [],
                body.baseline.model_dump(), body.candidate.model_dump(), body.repeats)
            run = EvalRun(id=str(uuid4()), dataset_id=dataset.id, project_id=dataset.project_id,
                          baseline=body.baseline.model_dump(), candidate=body.candidate.model_dump(),
                          repeats=body.repeats, state="complete", results=results,
                          created_by=account_id)
            session.add(run)
            session.flush()
            if project is not None and project.org_id is not None:
                audit(session, project.org_id, "eval.run", run.id, account_id)
            return run_dict(run)

    @app.get("/api/datasets/{id}/runs")
    def list_runs(request: Request, id: str):
        with sessions() as session:
            dataset = session.get(EvalDataset, id)
            if dataset is None:
                raise HTTPException(404, "Dataset not found")
            project = session.get(Project, dataset.project_id)
            if project is not None:
                dashboard_access(request, session, project)
            return [run_dict(r) for r in session.scalars(
                select(EvalRun).where(EvalRun.dataset_id == dataset.id)
                .order_by(EvalRun.created_at))]

    # ---- Phase 9: improvements and delivery ----

    def improvement_access(request, db_session, project_id, minimum):
        project = db_session.get(Project, project_id)
        if project is None:
            raise HTTPException(404, "Project not found")
        dashboard_access(request, db_session, project)
        resolved = session_auth(request, db_session)
        if project.org_id is not None:
            if resolved is None:
                if minimum == "admin":
                    raise HTTPException(401, "Login required")
            else:
                try:
                    require_project_role(db_session, project, resolved[1].id, minimum)
                except PermissionError:
                    raise HTTPException(403, "Insufficient role")
        return project

    @app.get("/api/projects/{id}/improvements")
    def list_improvements(request: Request, id: str):
        with sessions() as session:
            improvement_access(request, session, id, "viewer")
            return [improve_mod.public_improvement(i) for i in session.scalars(
                select(Improvement).where(Improvement.project_id == id)
                .order_by(Improvement.created_at))]

    @app.get("/api/improvements/{id}")
    def get_improvement(request: Request, id: str):
        with sessions() as session:
            imp = session.get(Improvement, id)
            if imp is None:
                raise HTTPException(404, "Improvement not found")
            improvement_access(request, session, imp.project_id, "viewer")
            prompts = [{"id": p.id, "path": p.path, "version": p.version, "status": p.status,
                        "content": p.content}
                       for p in session.scalars(select(PromptVersion).where(
                           PromptVersion.improvement_id == imp.id).order_by(PromptVersion.version))]
            return {**improve_mod.public_improvement(imp), "prompts": prompts}

    @app.post("/api/projects/{id}/improvements", status_code=201)
    def create_improvement(request: Request, id: str, body: ImprovementInput):
        with sessions.begin() as session:
            project = improvement_access(request, session, id, "member")
            account_id = None
            resolved = session_auth(request, session)
            if resolved is not None:
                account_id = resolved[1].id
            evidence, evidence_text = [], ""
            if body.evidence_event_id:
                event = session.scalars(select(Event).where(
                    Event.project_id == project.id, Event.id == body.evidence_event_id)).first()
                if event is None:
                    raise HTTPException(404, "Evidence event not found")
                evidence = [{"event_id": event.id, "conversation_id": event.conversation_id,
                             "content": event.content[:280]}]
                evidence_text = event.content
            draft = improve_mod.suggest(body.signal_kind, body.tool, evidence_text)
            if body.prompt_path:
                draft["prompt_path"] = body.prompt_path.strip()[:200] or draft["prompt_path"]
                draft["candidate_diff"] = draft["candidate_diff"].replace(
                    "prompts/support-agent.md", draft["prompt_path"], 1)
            imp = Improvement(id=str(uuid4()), project_id=project.id, title=draft["title"],
                              signal_kind=body.signal_kind, evidence=evidence,
                              cause=draft["cause"], uncertainty=draft["uncertainty"],
                              candidate_diff=draft["candidate_diff"], state="proposed",
                              created_by=account_id)
            session.add(imp)
            session.flush()
            if project.org_id is not None:
                audit(session, project.org_id, "improvement.create", imp.id, account_id)
            return improve_mod.public_improvement(imp)

    @app.post("/api/improvements/{id}/eval")
    def attach_eval(request: Request, id: str, body: ImprovementEval):
        with sessions.begin() as session:
            imp = session.get(Improvement, id)
            if imp is None:
                raise HTTPException(404, "Improvement not found")
            project = improvement_access(request, session, imp.project_id, "member")
            run = session.get(EvalRun, body.eval_run_id)
            if run is None or run.project_id != imp.project_id:
                raise HTTPException(404, "Evaluation run not found")
            imp.eval_run_id = run.id
            imp.updated_at = utc_now()
            resolved = session_auth(request, session)
            if project.org_id is not None:
                audit(session, project.org_id, "improvement.eval", imp.id,
                      resolved[1].id if resolved else None)
            return improve_mod.public_improvement(imp)

    @app.post("/api/improvements/{id}/transition")
    def transition_improvement(request: Request, id: str, body: ImprovementTransition):
        approve_states = {"deployed", "rolled_back", "cancelled"}
        with sessions.begin() as session:
            imp = session.get(Improvement, id)
            if imp is None:
                raise HTTPException(404, "Improvement not found")
            minimum = "admin" if body.to in approve_states else "member"
            project = improvement_access(request, session, imp.project_id, minimum)
            resolved = session_auth(request, session)
            account_id = resolved[1].id if resolved else None
            ok, reason = improve_mod.check_transition(imp, body.to, session)
            if not ok:
                raise HTTPException(422, reason)
            if body.to == "deployed":
                path, added = improve_mod.parse_prompt_block(imp.candidate_diff)
                improve_mod.activate_prompt(session, imp.project_id, path,
                                            "\n".join(added), imp.id, account_id)
                imp.approved_by = account_id
                imp.deployed_at = utc_now()
            if body.to == "rolled_back":
                path, _ = improve_mod.parse_prompt_block(imp.candidate_diff)
                improve_mod.rollback_prompt(session, imp.project_id, path)
            if body.to in ("resolved", "rolled_back"):
                imp.measurements = improve_mod.measure_outcome(
                    session, imp.project_id, imp.signal_kind, imp.deployed_at)
            imp.state = body.to
            imp.updated_at = utc_now()
            if project.org_id is not None:
                audit(session, project.org_id, f"improvement.{body.to}", imp.id, account_id)
            return improve_mod.public_improvement(imp)

    @app.get("/api/improvements/{id}/measurements")
    def improvement_measurements(request: Request, id: str, window_days: int = Query(default=7, ge=1, le=90)):
        with sessions() as session:
            imp = session.get(Improvement, id)
            if imp is None:
                raise HTTPException(404, "Improvement not found")
            improvement_access(request, session, imp.project_id, "viewer")
            return {"improvement_id": imp.id,
                    **improve_mod.measure_outcome(session, imp.project_id, imp.signal_kind,
                                                  imp.deployed_at, window_days)}

    @app.get("/api/projects/{id}/prompts")
    def list_prompts(request: Request, id: str):
        with sessions() as session:
            improvement_access(request, session, id, "viewer")
            return [{"id": p.id, "path": p.path, "version": p.version, "status": p.status,
                     "improvement_id": p.improvement_id,
                     "created_at": iso(p.created_at)}
                    for p in session.scalars(select(PromptVersion).where(
                        PromptVersion.project_id == id).order_by(PromptVersion.path, PromptVersion.version))]

    # ---- Phase 10: hosted MCP server ----

    def mcp_auth(request):
        header = request.headers.get("authorization", "")
        if not header.startswith(f"Bearer {SESSION_PREFIX}"):
            return None
        with sessions() as session:
            resolved = resolve_session(session, header[len("Bearer "):])
            return resolved[1].id if resolved else None

    def mcp_project(db_session, account_id, project_id):
        project = db_session.get(Project, project_id)
        if project is None or (project.org_id is None):
            return None, "not_found"
        membership = db_session.get(Membership, (project.org_id, account_id))
        if membership is None:
            return None, "not_found"
        return project, "ok"

    def mcp_trim(value, limit=2000):
        if isinstance(value, str):
            return value[:limit]
        if isinstance(value, list):
            return [mcp_trim(item, limit) for item in value[:50]]
        if isinstance(value, dict):
            return {key: mcp_trim(item, limit) for key, item in list(value.items())[:50]}
        return value

    @app.post("/mcp")
    async def mcp_endpoint(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(status_code=200, content=mcp_mod.error(None, mcp_mod.ERROR_PARSE, "Invalid JSON"))
        request_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}
        if method == "initialize":
            return JSONResponse(content=mcp_mod.result(request_id, {
                "protocolVersion": mcp_mod.PROTOCOL_VERSION, "serverInfo": mcp_mod.SERVER_INFO,
                "capabilities": {"tools": {}}}))
        if method in ("notifications/initialized", "notifications/cancelled"):
            return JSONResponse(content=mcp_mod.result(request_id, {}))
        if method == "tools/list":
            account_id = mcp_auth(request)
            if account_id is None:
                return JSONResponse(content=mcp_mod.error(request_id, mcp_mod.ERROR_UNAUTHORIZED, "Login required"))
            return JSONResponse(content=mcp_mod.result(request_id, {"tools": mcp_mod.TOOLS}))
        if method != "tools/call":
            return JSONResponse(content=mcp_mod.error(request_id, mcp_mod.ERROR_METHOD_NOT_FOUND, f"Unknown method {method}"))
        account_id = mcp_auth(request)
        if account_id is None:
            return JSONResponse(content=mcp_mod.error(request_id, mcp_mod.ERROR_UNAUTHORIZED, "Login required"))
        name = (params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return JSONResponse(content=mcp_mod.error(request_id, mcp_mod.ERROR_INVALID_PARAMS, "arguments must be an object"))
        try:
            with sessions.begin() as session:
                payload = mcp_tool(session, account_id, name, arguments)
        except HTTPException as error:
            code = {401: mcp_mod.ERROR_UNAUTHORIZED, 403: mcp_mod.ERROR_FORBIDDEN,
                    404: mcp_mod.ERROR_NOT_FOUND, 422: mcp_mod.ERROR_INVALID_PARAMS}.get(
                        error.status_code, mcp_mod.ERROR_INVALID_PARAMS)
            return JSONResponse(content=mcp_mod.error(request_id, code, error.detail))
        return JSONResponse(content=mcp_mod.text_result(request_id, payload))

    def mcp_tool(db_session, account_id, name, arguments):
        if name == "tervik_ops_summary":
            return mcp_ops(db_session, account_id)
        if name in ("tervik_list_conversations", "tervik_list_clusters", "tervik_list_intents"):
            project_id = arguments.get("project_id")
            if not project_id:
                raise HTTPException(422, "project_id is required")
            project, status = mcp_project(db_session, account_id, project_id)
            if project is None:
                raise HTTPException(404, "Project not found")
            window_range = arguments.get("range", "7d")
            if window_range not in ("24h", "7d", "30d"):
                raise HTTPException(422, "Invalid range")
            audit(db_session, project.org_id, "mcp.call", name, account_id)
            if name == "tervik_list_conversations":
                events, signals, _ = project_analysis(db_session, project.id)
                start, end = window(window_range)
                rows = analysis.conversation_summaries(
                    analysis.in_range(events, start, end),
                    analysis.signals_in_range(signals, start, end))
                search = (arguments.get("search") or "").casefold()
                if search:
                    rows = [r for r in rows if search in (r["preview"] or "").casefold()]
                if arguments.get("flagged_only"):
                    rows = [r for r in rows if r["status"] == "flagged"]
                return mcp_trim(rows[:50])
            if name == "tervik_list_clusters":
                events, signals, states = project_analysis(db_session, project.id)
                start, end = window(window_range)
                rows = analysis.clusters(project.id, events, signals, states, start, end)
                wanted = arguments.get("status")
                if wanted:
                    rows = [r for r in rows if r["status"] == wanted]
                return mcp_trim(rows[:50])
            intents = db_session.scalars(select(Intent).where(
                Intent.project_id == project.id, Intent.enabled == True)).all()  # noqa: E712
            return [{"id": i.id, "name": i.name, "description": i.description,
                     "examples": i.examples, "version": i.version} for i in intents[:50]]
        if name == "tervik_get_conversation":
            conversation_id = arguments.get("conversation_id")
            if not conversation_id:
                raise HTTPException(422, "conversation_id is required")
            events = list(db_session.scalars(select(Event).where(
                Event.conversation_id == conversation_id).order_by(Event.timestamp, Event.id)))
            if not events:
                raise HTTPException(404, "Conversation not found")
            project, status = mcp_project(db_session, account_id, events[0].project_id)
            if project is None:
                raise HTTPException(404, "Conversation not found")
            audit(db_session, project.org_id, "mcp.call", name, account_id)
            signals = analysis.analyze(events)
            return mcp_trim({**analysis.summary(events, signals),
                             "messages": [analysis.event_dict(e) for e in events],
                             "signals": [analysis.public_signal(s) for s in signals],
                             "spans": analysis.spans(events)})
        if name == "tervik_get_cluster":
            cluster_id = arguments.get("cluster_id")
            if not cluster_id:
                raise HTTPException(422, "cluster_id is required")
            window_range = arguments.get("range", "7d")
            if window_range not in ("24h", "7d", "30d"):
                raise HTTPException(422, "Invalid range")
            row, conversations, evidence = locate_cluster(db_session, cluster_id, window_range)
            project, status = mcp_project(db_session, account_id, row["project_id"])
            if project is None:
                raise HTTPException(404, "Cluster not found")
            audit(db_session, project.org_id, "mcp.call", name, account_id)
            return mcp_trim({**row, "conversations": conversations, "evidence": evidence})
        if name == "tervik_get_improvement":
            improvement_id = arguments.get("improvement_id")
            if not improvement_id:
                raise HTTPException(422, "improvement_id is required")
            imp = db_session.get(Improvement, improvement_id)
            if imp is None:
                raise HTTPException(404, "Improvement not found")
            project, status = mcp_project(db_session, account_id, imp.project_id)
            if project is None:
                raise HTTPException(404, "Improvement not found")
            audit(db_session, project.org_id, "mcp.call", name, account_id)
            return mcp_trim(improve_mod.public_improvement(imp))
        raise HTTPException(422, f"Unknown tool {name}")

    def mcp_ops(db_session, account_id):
        org_ids = [m.org_id for m in db_session.scalars(
            select(Membership).where(Membership.account_id == account_id))]
        project_ids = list(db_session.scalars(select(Project.id).where(
            Project.org_id.in_(org_ids)))) if org_ids else []
        jobs = select(IngestionJob.state, func.count()).group_by(IngestionJob.state)
        if project_ids:
            jobs = jobs.where(IngestionJob.project_id.in_(project_ids))
        else:
            jobs = jobs.where(IngestionJob.project_id == "__none__")
        backlog = {state: count for state, count in db_session.execute(jobs).all()}
        return {"backlog": backlog, "projects": len(project_ids)}

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
                project = session.get(Project, DEMO_PROJECT_ID)
            before = session.execute(select(func.count()).select_from(Event).where(
                Event.project_id == DEMO_PROJECT_ID)).scalar_one()
            queue_mod.enqueue_events(session, engine, project, demo_events(utc_now()))
        if settings.inline_process:
            with sessions.begin() as session:
                queue_mod.process_pending(session, engine, settings, project_id=DEMO_PROJECT_ID)
        with sessions() as session:
            after = session.execute(select(func.count()).select_from(Event).where(
                Event.project_id == DEMO_PROJECT_ID)).scalar_one()
        if settings.clickhouse_url:
            background_tasks.add_task(retry_mirrors_task, DEMO_PROJECT_ID)
        return {"seeded": after > before, "project_id": DEMO_PROJECT_ID}

    return app


app = create_app()
