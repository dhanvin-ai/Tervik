"""Session and event capture API (`/api/v1/capture-session`, `/api/v1/capture-event`).

This is the interaction-shaped ingestion contract: a client starts a session
once per conversation, then records each operation as one event. An event is
either a turn pair (the user's input and the agent's output together) or a
tool call that points at the turn or tool that triggered it via `parent_id`.

Events are mapped onto the message-level rows that detection, discovery, and
the dashboard already read, so both ingestion paths share one analysis:

- turn pair  -> a user message (input) and an assistant message (output)
- tool call  -> a tool message nested under its parent span

Timestamps and latency arrive in milliseconds.
"""
from datetime import datetime, timedelta, timezone
import json
from typing import Any
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update

from .db import ConversationSession, EndUser, Event, utc_now
from .schemas import EventInput

MAX_TEXT = 32_000
MAX_TRAITS = 50
MAX_TRAIT_CHARS = 500


def _scalar_text(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, allow_nan=False, default=str)


def _string_map(value: dict, label: str) -> dict:
    if len(value) > MAX_TRAITS:
        raise ValueError(f"{label} accepts at most {MAX_TRAITS} keys")
    cleaned = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip() or len(key) > 100:
            raise ValueError(f"{label} keys must be non-blank strings of at most 100 characters")
        if item is None:
            continue
        text = _scalar_text(item)
        if len(text) > MAX_TRAIT_CHARS:
            raise ValueError(f"{label} values must be at most {MAX_TRAIT_CHARS} characters")
        cleaned[key] = text
    return cleaned


def from_millis(value: int | None) -> datetime:
    if value is None:
        return utc_now()
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


class SessionCapture(BaseModel):
    model_config = ConfigDict(extra="ignore")
    session_id: str = Field(min_length=1, max_length=200)
    user_data: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: int | None = Field(default=None, ge=0, strict=True)
    client_config: str | None = Field(default=None, max_length=200)

    @field_validator("session_id")
    @classmethod
    def nonblank(cls, value: str):
        if not value.strip():
            raise ValueError("session_id cannot be blank")
        return value

    @field_validator("user_data")
    @classmethod
    def user_identity(cls, value: dict):
        user_id = value.get("user_id")
        if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 200:
            raise ValueError("user_data.user_id must be a non-blank string of at most 200 characters")
        return _string_map(value, "user_data")

    @field_validator("metadata")
    @classmethod
    def session_metadata(cls, value: dict):
        return _string_map(value, "metadata")


class EventCapture(BaseModel):
    model_config = ConfigDict(extra="ignore")
    event_id: str = Field(min_length=1, max_length=180)
    session_id: str = Field(min_length=1, max_length=200)
    primitive_name: str = Field(min_length=1, max_length=200)
    args: Any = ""
    result: Any = ""
    success: bool = True
    latency: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    timestamp: int | None = Field(default=None, ge=0, strict=True)
    parent_id: str | None = Field(default=None, max_length=180)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_id", "session_id", "primitive_name")
    @classmethod
    def nonblank(cls, value: str):
        if not value.strip():
            raise ValueError("identifier cannot be blank")
        return value

    @field_validator("args", "result")
    @classmethod
    def text_payload(cls, value):
        text = "" if value is None else _scalar_text(value)
        if len(text) > MAX_TEXT:
            raise ValueError(f"must be at most {MAX_TEXT} characters")
        return text

    @field_validator("metadata")
    @classmethod
    def event_metadata(cls, value: dict):
        return _string_map(value, "metadata")


def conversation_uuid(project_id: str, session_id: str) -> str:
    return str(uuid5(UUID(project_id), session_id))


def upsert_end_user(db_session, project_id: str, user_id: str, traits: dict, seen_at: datetime):
    user = db_session.get(EndUser, (project_id, user_id))
    if user is None:
        user = EndUser(project_id=project_id, user_id=user_id, traits=dict(traits),
                       first_seen=seen_at, last_seen=seen_at)
        db_session.add(user)
    else:
        user.traits = {**(user.traits or {}), **traits}
        if seen_at > _aware(user.last_seen):
            user.last_seen = seen_at
        if seen_at < _aware(user.first_seen):
            user.first_seen = seen_at
    return user


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def upsert_session(db_session, project_id: str, body: SessionCapture) -> ConversationSession:
    """Create the session, or merge traits and metadata into an existing one."""
    started_at = from_millis(body.timestamp)
    traits = {key: value for key, value in body.user_data.items() if key != "user_id"}
    user_id = body.user_data["user_id"]
    row = db_session.get(ConversationSession, (project_id, body.session_id))
    if row is None:
        row = ConversationSession(project_id=project_id, id=body.session_id,
                                  conversation_id=conversation_uuid(project_id, body.session_id),
                                  user_id=user_id, user_data=dict(body.user_data),
                                  session_metadata=dict(body.metadata), client_config=body.client_config,
                                  started_at=started_at, updated_at=utc_now())
        db_session.add(row)
    else:
        row.user_id = user_id
        row.user_data = {**(row.user_data or {}), **body.user_data}
        row.session_metadata = {**(row.session_metadata or {}), **body.metadata}
        row.client_config = body.client_config or row.client_config
        row.updated_at = utc_now()
    upsert_end_user(db_session, project_id, user_id, traits, started_at)
    # Events that arrived before their session carry no user yet.
    db_session.execute(update(Event).where(
        Event.project_id == project_id, Event.conversation_id == row.conversation_id,
        Event.user_id.is_(None)).values(user_id=user_id))
    db_session.flush()
    return row


def implicit_session(db_session, project_id: str, session_id: str, at: datetime) -> ConversationSession:
    """Events may arrive before their session (or without one). Record the
    boundary anyway so the conversation stays whole; identity stays unknown."""
    row = db_session.get(ConversationSession, (project_id, session_id))
    if row is None:
        row = ConversationSession(project_id=project_id, id=session_id,
                                  conversation_id=conversation_uuid(project_id, session_id),
                                  user_id=None, user_data={}, session_metadata={},
                                  started_at=at, updated_at=utc_now())
        db_session.add(row)
        db_session.flush()
    return row


def _number(metadata: dict, *keys, kind=float):
    for key in keys:
        value = metadata.get(key)
        if value is None:
            continue
        try:
            number = kind(float(value)) if kind is int else kind(value)
        except (TypeError, ValueError):
            continue
        if number >= 0 and number == number and number != float("inf"):
            return number
    return None


def resolve_trace(db_session, project_id: str, parent_id: str | None, event_id: str) -> str:
    """A tool call joins its root turn's trace when the parent is already stored;
    otherwise it uses the parent id, which is the turn id for direct children."""
    if not parent_id:
        return event_id
    parent = db_session.scalars(select(Event.trace_id).where(
        Event.project_id == project_id, Event.span_id == parent_id)).first()
    return parent or parent_id


def reroot_children(db_session, project_id: str, event_id: str, trace_id: str):
    """Children captured before their parent point at the parent's id; move them
    onto the parent's trace once the parent arrives."""
    if trace_id != event_id:
        db_session.execute(update(Event).where(
            Event.project_id == project_id, Event.trace_id == event_id).values(trace_id=trace_id))


def to_events(body: EventCapture, session_row: ConversationSession, trace_id: str) -> list[EventInput]:
    """Map one captured operation onto message-level events."""
    at = from_millis(body.timestamp)
    latency = body.latency
    status = "success" if body.success else "error"
    metadata = dict(body.metadata)
    model = metadata.get("model")
    tokens = _number(metadata, "tokens", "total_tokens", kind=int)
    cost = _number(metadata, "cost_usd", "cost")
    shared = {"conversation_id": session_row.id, "user_id": session_row.user_id, "trace_id": trace_id}
    common_meta = {**metadata, "capture_event_id": body.event_id, "primitive_name": body.primitive_name}
    if body.parent_id:
        return [EventInput(id=body.event_id, role="tool", content=body.result, timestamp=at,
                           span_id=body.event_id, parent_span_id=body.parent_id, name=body.primitive_name,
                           status=status, latency_ms=latency, tokens=tokens, cost_usd=cost,
                           model=model[:200] if model else None,
                           metadata={**common_meta, "event_type": "tool_call",
                                     "input": body.args, "output": body.result}, **shared)]
    # The reply lands when the turn finishes, after any tool calls it made.
    # Clients that stamp the end time already would push it into the future.
    ended = max(at, min(at + timedelta(milliseconds=latency or 0), utc_now()))
    events = []
    if body.args:
        events.append(EventInput(id=f"{body.event_id}:input", role="user", content=body.args, timestamp=at,
                                 metadata={**common_meta, "event_type": "turn"}, **shared))
    events.append(EventInput(id=f"{body.event_id}:output", role="assistant", content=body.result,
                             timestamp=ended, span_id=body.event_id, name=body.primitive_name, status=status,
                             latency_ms=latency, tokens=tokens, cost_usd=cost, model=model[:200] if model else None,
                             metadata={**common_meta, "event_type": "turn", "input": body.args,
                                       "output": body.result}, **shared))
    return events
