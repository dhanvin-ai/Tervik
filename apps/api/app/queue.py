"""Phase 2 durable ingestion outbox.

Contract:
- Ack follows a durable jobs commit. Inline processing is best-effort.
- One row per (project_id, event_id) everywhere: jobs, events, usage.
  Retries add zero rows and never double-charge usage.
- Workers only commit required sinks before marking jobs processed.
- Error codes are safe strings; payloads never enter logs or diagnostics.
"""
import hashlib
import logging
from datetime import timedelta
from uuid import UUID, uuid5

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .capture import apply_capture, project_settings, retention_cutoff
from .db import (AnalyzedConversation, Classification, ConversationSession, Event, IngestionJob, PayloadObject,
                 Project, UsageRecord, utc, utc_now)

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
MIRROR_MAX_ATTEMPTS = 8
RETRY_DELAYS = [30, 300, 1800, 7200, 43200]  # seconds
LARGE_PAYLOAD_CHARS = 8000


def _insert(engine):
    return sqlite_insert if engine.dialect.name == "sqlite" else postgres_insert


def enqueue_events(session, engine, project: Project, events, *, environment: str = "production"):
    """Durable acceptance. Returns (accepted, duplicates, expired)."""
    insert = _insert(engine)
    settings = project_settings(project)
    retention_days = int(settings.get("retention_days", 90))
    cutoff = retention_cutoff(retention_days, utc_now())
    accepted, duplicates, expired = 0, 0, 0
    for event in events:
        values = event.model_dump()
        values["source_conversation_id"] = values.pop("conversation_id")
        values["conversation_id"] = str(uuid5(UUID(project.id), values["source_conversation_id"]))
        values["event_metadata"] = values.pop("metadata")
        values["timestamp"] = utc(values["timestamp"])
        content, metadata = apply_capture(values.get("content", ""), values.get("event_metadata") or {}, settings)
        values["content"] = content
        values["event_metadata"] = metadata
        source_time = utc(values["timestamp"])
        if source_time < cutoff:
            expired += 1
        payload = {
            **{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in values.items()},
        }
        row = {"project_id": project.id, "event_id": values["id"], "environment": environment,
               "payload": payload,
               "state": "expired" if source_time < cutoff else "pending",
               "error_code": "expired_retention" if source_time < cutoff else None}
        result = session.execute(insert(IngestionJob).values(**row).on_conflict_do_nothing(
            index_elements=["project_id", "event_id"]).returning(IngestionJob.event_id)).scalar_one_or_none()
        if result is None:
            duplicates += 1
        else:
            accepted += 1
    return accepted, duplicates, expired


def _write_event(session, engine, project_id: str, org_id: str | None, job: IngestionJob) -> dict | None:
    """Idempotent materialization of one job. Returns mirror row or None."""
    payload = dict(job.payload)
    values = {
        "project_id": project_id, "id": job.event_id,
        "conversation_id": payload["conversation_id"],
        "source_conversation_id": payload.get("source_conversation_id", ""),
        "user_id": payload.get("user_id"), "role": payload.get("role", "assistant"),
        "content": payload.get("content", ""), "timestamp": utc(_parse_time(payload.get("timestamp"))),
        "trace_id": payload.get("trace_id"), "span_id": payload.get("span_id"),
        "parent_span_id": payload.get("parent_span_id"), "name": payload.get("name"),
        "status": payload.get("status", "success"), "latency_ms": payload.get("latency_ms"),
        "tokens": payload.get("tokens"), "cost_usd": payload.get("cost_usd"),
        "model": payload.get("model"), "event_metadata": payload.get("event_metadata") or {},
        "org_id": org_id, "environment": job.environment or "production",
        "schema_version": 2, "ingested_at": utc_now(),
    }
    insert = _insert(engine)
    inserted = session.execute(insert(Event).values(**values).on_conflict_do_nothing(
        index_elements=["project_id", "id"]).returning(Event.id)).scalar_one_or_none()
    content = values["content"] or ""
    session.execute(insert(UsageRecord).values(
        project_id=project_id, event_id=job.event_id, bytes=len(content.encode("utf-8", "ignore")),
    ).on_conflict_do_nothing(index_elements=["project_id", "event_id"]))
    if len(content) >= LARGE_PAYLOAD_CHARS:
        digest = hashlib.sha256(content.encode("utf-8", "ignore")).hexdigest()
        key = f"{project_id}/{job.event_id}/{digest[:16]}"
        session.execute(insert(PayloadObject).values(
            key=key, project_id=project_id, digest=digest, size=len(content),
            content=content[:200_000],
        ).on_conflict_do_nothing(index_elements=["key"]))
    if inserted is None:
        return None
    return {"project_id": project_id, "id": values["id"], "conversation_id": values["conversation_id"],
            "datetime": values["timestamp"], "role": values["role"],
            "payload": {"id": values["id"], "role": values["role"], "content": content,
                        "metadata": values["event_metadata"]}}


def _parse_time(value):
    from datetime import datetime
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def process_pending(session, engine, settings, *, project_id: str | None = None, limit: int = 500):
    """Process pending/failed-due jobs. Safe to run concurrently; rows win once."""
    from .db import Project as ProjectModel
    from .mirror import mirror_events
    now = utc_now()
    query = select(IngestionJob).where(IngestionJob.state.in_(("pending", "failed")))
    if project_id:
        query = query.where(IngestionJob.project_id == project_id)
    query = query.where((IngestionJob.next_retry_at.is_(None)) | (IngestionJob.next_retry_at <= now)).limit(limit)
    jobs = list(session.scalars(query))
    mirror_batch, mirror_jobs = [], []
    for job in jobs:
        if job.state == "expired":
            continue
        try:
            project = session.get(ProjectModel, job.project_id)
            if project is None:
                job.state, job.error_code = "dead", "unknown_project"
                continue
            row = _write_event(session, engine, job.project_id, project.org_id, job)
            job.state, job.error_code, job.next_retry_at = "processed", None, None
            job.updated_at = utc_now()
            if row is not None:
                mirror_batch.append(row)
                mirror_jobs.append(job)
        except Exception:
            logger.warning("ingestion job processing failed; scheduled retry")
            job.retry_count = (job.retry_count or 0) + 1
            if job.retry_count >= MAX_RETRIES:
                job.state, job.error_code = "dead", "processing_failed"
            else:
                delay = RETRY_DELAYS[min(job.retry_count - 1, len(RETRY_DELAYS) - 1)]
                job.state, job.error_code = "failed", "processing_failed"
                job.next_retry_at = utc_now() + timedelta(seconds=delay)
            job.updated_at = utc_now()
    session.flush()
    # Mirror is retryable and never fails the committed SQL event.
    if mirror_batch and getattr(settings, "clickhouse_url", None):
        try:
            mirror_events(settings, mirror_batch)
            for job in mirror_jobs:
                job.mirror_state, job.mirror_attempts = "done", (job.mirror_attempts or 0) + 1
        except Exception:
            logger.warning("clickhouse mirror batch deferred")
            for job in mirror_jobs:
                job.mirror_attempts = (job.mirror_attempts or 0) + 1
                job.mirror_state = "failed" if job.mirror_attempts >= MIRROR_MAX_ATTEMPTS else "pending"
    return len(jobs)


def retry_mirrors(session, settings, *, limit: int = 500):
    from .mirror import mirror_events
    if not getattr(settings, "clickhouse_url", None):
        return 0
    jobs = list(session.scalars(select(IngestionJob).where(
        IngestionJob.state == "processed", IngestionJob.mirror_state != "done").limit(limit)))
    if not jobs:
        return 0
    batch = []
    for job in jobs:
        payload = job.payload or {}
        batch.append({"project_id": job.project_id, "id": job.event_id,
                      "conversation_id": payload.get("conversation_id", ""),
                      "datetime": _parse_time(payload.get("timestamp", utc_now().isoformat())),
                      "role": payload.get("role", "assistant"),
                      "payload": {"id": job.event_id, "role": payload.get("role"),
                                  "content": payload.get("content", ""),
                                  "metadata": payload.get("event_metadata", {})}})
    try:
        mirror_events(settings, batch)
        for job in jobs:
            job.mirror_state, job.mirror_attempts = "done", (job.mirror_attempts or 0) + 1
        return len(jobs)
    except Exception:
        for job in jobs:
            job.mirror_attempts = (job.mirror_attempts or 0) + 1
            job.mirror_state = "failed" if job.mirror_attempts >= MIRROR_MAX_ATTEMPTS else "pending"
        return 0


def job_stats(session, project_id: str) -> dict:
    rows = session.execute(select(IngestionJob.state, func.count()).where(
        IngestionJob.project_id == project_id).group_by(IngestionJob.state)).all()
    stats = {state: 0 for state in ("pending", "processed", "failed", "dead", "expired")}
    for state, count in rows:
        stats[state] = count
    usage = session.execute(select(func.count(), func.coalesce(func.sum(UsageRecord.bytes), 0)).where(
        UsageRecord.project_id == project_id)).one()
    return {"jobs": stats, "usage_events": usage[0], "usage_bytes": int(usage[1] or 0)}


def run_retention(session, engine, project: Project) -> dict:
    """Delete expired telemetry from SQL projections and payload objects."""
    settings = project_settings(project)
    cutoff = retention_cutoff(int(settings.get("retention_days", 90)), utc_now())
    expired_events = session.execute(select(Event.project_id, Event.id).where(
        Event.project_id == project.id, Event.timestamp < cutoff).limit(2000)).all()
    removed = 0
    for _, event_id in expired_events:
        session.execute(delete(Event).where(Event.project_id == project.id, Event.id == event_id))
        session.execute(delete(UsageRecord).where(UsageRecord.project_id == project.id, UsageRecord.event_id == event_id))
        session.execute(delete(IngestionJob).where(IngestionJob.project_id == project.id, IngestionJob.event_id == event_id))
        removed += 1
    session.execute(delete(PayloadObject).where(
        PayloadObject.project_id == project.id,
        PayloadObject.retention_deadline.is_not(None),
        PayloadObject.retention_deadline < utc_now()))
    # Findings and sessions expire with the telemetry they describe.
    session.execute(delete(Classification).where(
        Classification.project_id == project.id, Classification.occurred_at < cutoff))
    session.execute(delete(AnalyzedConversation).where(
        AnalyzedConversation.project_id == project.id, AnalyzedConversation.last_event_at < cutoff))
    live = select(Event.conversation_id).where(Event.project_id == project.id)
    session.execute(delete(ConversationSession).where(
        ConversationSession.project_id == project.id, ConversationSession.started_at < cutoff,
        ConversationSession.conversation_id.not_in(live)))
    return {"removed_events": removed, "cutoff": cutoff.isoformat().replace("+00:00", "Z")}
