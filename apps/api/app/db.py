from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.engine import make_url
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc)


def utc(value: datetime):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def iso(value: datetime):
    return utc(value).isoformat().replace("+00:00", "Z")


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(160), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    api_key: Mapped[str] = mapped_column(String(128))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Phase 2: organization ownership. Null = Phase 1 legacy project (isolated).
    org_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=True, index=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)


class Organization(Base):
    """Phase 2 tenant root. Owns projects, memberships, credentials, and audit."""
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Account(Base):
    """Phase 2 dashboard user. Distinct from the customer's end users."""
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Membership(Base):
    __tablename__ = "memberships"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Session(Base):
    """Hashed dashboard session. The raw token is returned once and never stored."""
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Environment(Base):
    __tablename__ = "environments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(80), default="production")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Credential(Base):
    """Scoped ingest credential. Secret is hashed; prefix is for display only."""
    __tablename__ = "credentials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    environment_id: Mapped[str | None] = mapped_column(ForeignKey("environments.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120), default="default")
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scope: Mapped[str] = mapped_column(String(20), default="ingest")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Event(Base):
    __tablename__ = "events"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    source_conversation_id: Mapped[str] = mapped_column(String(200))
    user_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    span_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    event_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    # Phase 2 canonical fields. Nullable/defaulted so Phase 1 rows stay valid.
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    environment: Mapped[str] = mapped_column(String(80), default="production")
    schema_version: Mapped[int] = mapped_column(Integer, default=2)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class IngestionJob(Base):
    """Durable outbox. Ack follows this commit; workers process afterwards."""
    __tablename__ = "ingestion_jobs"
    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    state: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    environment: Mapped[str] = mapped_column(String(80), default="production")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    mirror_state: Mapped[str] = mapped_column(String(20), default="pending")
    mirror_attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class UsageRecord(Base):
    """Idempotent usage. One row per logical event; retries never add rows."""
    __tablename__ = "usage_records"
    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PayloadObject(Base):
    """Large/redacted payload store. Local adapter; S3 when configured."""
    __tablename__ = "payload_objects"
    key: Mapped[str] = mapped_column(String(320), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    digest: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer, default=0)
    content_type: Mapped[str] = mapped_column(String(120), default="application/json")
    retention_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditRecord(Base):
    __tablename__ = "audit_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    resource: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BehaviorRule(Base):
    """Phase 5 customer-defined behavior rule. Evaluated deterministically."""
    __tablename__ = "behavior_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))
    pattern: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tool: Mapped[str | None] = mapped_column(String(200), nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="high")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[str] = mapped_column(String(20), default="1")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Intent(Base):
    """Phase 6 configured intent: customer-owned definition that works
    before the project has substantial traffic."""
    __tablename__ = "intents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    examples: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[str] = mapped_column(String(20), default="1")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SemanticCluster(Base):
    """Phase 6 discovered topic. `key` is the deterministic group identity;
    `label` is editable without touching evidence."""
    __tablename__ = "semantic_clusters"
    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_semantic_cluster_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    label_override: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")
    merged_into: Mapped[str | None] = mapped_column(String(36), nullable=True)
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SemanticMembership(Base):
    __tablename__ = "semantic_memberships"
    cluster_id: Mapped[str] = mapped_column(ForeignKey("semantic_clusters.id"), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)


class AlertRule(Base):
    """Phase 7 alert rule. Threshold, trend, or daily summary cadence."""
    __tablename__ = "alert_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))
    signal_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    threshold: Mapped[float] = mapped_column(Float, default=0)
    window_hours: Mapped[int] = mapped_column(Integer, default=24)
    min_samples: Mapped[int] = mapped_column(Integer, default=10)
    cooldown_hours: Mapped[int] = mapped_column(Integer, default=24)
    channels: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    state: Mapped[str] = mapped_column(String(20), default="ok")
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AlertDelivery(Base):
    """One delivery attempt series. Secrets never stored: only a target hash."""
    __tablename__ = "alert_deliveries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("alert_rules.id"), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    dedup_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    state: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    channel_type: Mapped[str] = mapped_column(String(20), default="webhook")
    target_hash: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Plan(Base):
    """Phase 7 usage plan per organization. Provider billing plugs in later."""
    __tablename__ = "plans"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(40), default="beta")
    monthly_event_limit: Mapped[int] = mapped_column(Integer, default=100000)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EvalDataset(Base):
    """Phase 8 evaluation dataset built from production findings + controls."""
    __tablename__ = "eval_datasets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[str] = mapped_column(String(20), default="1")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    cases: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EvalRun(Base):
    """Phase 8 baseline-vs-candidate comparison with reproducible artifacts."""
    __tablename__ = "eval_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("eval_datasets.id"), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    baseline: Mapped[dict] = mapped_column(JSON, default=dict)
    candidate: Mapped[dict] = mapped_column(JSON, default=dict)
    repeats: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(20), default="complete")
    results: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ClusterState(Base):
    __tablename__ = "cluster_states"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open")


def make_database(url: str):
    kwargs = {}
    if url.startswith("sqlite"):
        path = make_url(url).database
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def sqlite_pragmas(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
