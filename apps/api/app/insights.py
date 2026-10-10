"""Operational analytics over captured events: the command-center summary,
tool-call reliability, the raw event log, errors, metadata breakdowns,
end users, cohort groups, and text search.

An *operation* is one agent turn (its assistant reply) or one tool call;
user messages are the input half of a turn, so they are not counted twice.
Everything here is computed from recorded rows and cites event ids.
"""
from collections import Counter, defaultdict
import csv
from datetime import timedelta
import io
import math
import re
from typing import Literal

from fastapi import HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import select

from . import analysis
from .db import ConversationSession, EndUser, Event, iso, utc, utc_now

InsightRange = Literal["1h", "24h", "7d", "30d", "90d", "all"]
RANGE_HOURS = {"1h": 1, "24h": 24, "7d": 168, "30d": 720, "90d": 2160}
OPERATION_ROLES = ("assistant", "tool")
# Keys the capture API adds for its own bookkeeping; not customer metadata.
INTERNAL_KEYS = {"input", "output", "capture_event_id", "primitive_name", "event_type"}
LIST_CONTENT_CHARS = 2000
NUMBERS = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\d+", re.I)


# ---- windows and buckets ----

def window(range: str, events=None):
    end = utc_now()
    if range == "all":
        stamps = [utc(e.timestamp) for e in events or []]
        return (min(stamps) if stamps else end - timedelta(days=1)), end
    return end - timedelta(hours=RANGE_HOURS[range]), end


def granularity(start, end):
    return "hour" if end - start <= timedelta(hours=48) else "day"


def bucket_key(timestamp, unit):
    value = utc(timestamp)
    if unit == "hour":
        return value.replace(minute=0, second=0, microsecond=0)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def empty_buckets(start, end, unit):
    step = timedelta(hours=1) if unit == "hour" else timedelta(days=1)
    cursor, buckets = bucket_key(start, unit), []
    while cursor <= end:
        buckets.append(cursor)
        cursor += step
    return buckets


def percentile(values, fraction):
    """Nearest-rank percentile; None when there is nothing to rank."""
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(fraction * len(ordered)) - 1)], 2)


def average(values):
    return round(sum(values) / len(values), 2) if values else None


def is_operation(event):
    return event.role in OPERATION_ROLES


def is_tool(event):
    return event.role == "tool"


# ---- command center ----

def summary(events, start, end):
    selected = analysis.in_range(events, start, end)
    operations = [e for e in selected if is_operation(e)]
    errors = [e for e in operations if e.status == "error"]
    latencies = [e.latency_ms for e in operations if e.latency_ms is not None]
    unit = granularity(start, end)
    buckets = {key: {"calls": 0, "errors": 0, "users": set(), "conversations": set()}
               for key in empty_buckets(start, end, unit)}
    for event in selected:
        bucket = buckets.setdefault(bucket_key(event.timestamp, unit),
                                    {"calls": 0, "errors": 0, "users": set(), "conversations": set()})
        bucket["conversations"].add(event.conversation_id)
        if event.user_id:
            bucket["users"].add(event.user_id)
        if is_operation(event):
            bucket["calls"] += 1
            bucket["errors"] += event.status == "error"
    agents = defaultdict(lambda: {"calls": 0, "errors": 0})
    for event in operations:
        if event.role == "assistant":
            row = agents[event.name or "agent"]
            row["calls"] += 1
            row["errors"] += event.status == "error"
    return {
        "start": iso(start), "end": iso(end), "granularity": unit,
        "total_calls": len(operations),
        "turns": sum(1 for e in operations if e.role == "assistant"),
        "tool_calls": sum(1 for e in operations if is_tool(e)),
        "total_conversations": len({e.conversation_id for e in selected}),
        "active_users": len({e.user_id for e in selected if e.user_id}),
        "errors": len(errors),
        "success_rate": round(100 * (len(operations) - len(errors)) / len(operations), 2) if operations else None,
        "avg_latency_ms": average(latencies),
        "p95_latency_ms": percentile(latencies, 0.95),
        "tokens": sum(e.tokens or 0 for e in selected),
        "cost_usd": round(sum(e.cost_usd or 0 for e in selected), 8),
        "timeline": [{"t": iso(key), "calls": value["calls"], "errors": value["errors"],
                      "users": len(value["users"]), "conversations": len(value["conversations"])}
                     for key, value in sorted(buckets.items())],
        "agents": sorted(({"name": name, **value} for name, value in agents.items()),
                         key=lambda row: (-row["calls"], row["name"])),
    }


# ---- tool calls ----

def error_message(event):
    text = (event.content or "").strip().splitlines()
    return (text[0] if text else "No error message recorded")[:240]


def error_groups(events, limit=5):
    groups = {}
    for event in sorted(events, key=lambda e: (utc(e.timestamp), e.id)):
        message = error_message(event)
        key = NUMBERS.sub("#", message.casefold())[:160]
        group = groups.setdefault(key, {"message": message, "count": 0, "example_event_id": event.id,
                                        "last_seen": iso(event.timestamp)})
        group["count"] += 1
        group["last_seen"] = iso(event.timestamp)
    return sorted(groups.values(), key=lambda g: (-g["count"], g["message"]))[:limit]


def tool_stats(events, start, end):
    selected = [e for e in analysis.in_range(events, start, end) if is_tool(e)]
    unit = granularity(start, end)
    grouped = defaultdict(list)
    for event in selected:
        grouped[event.name or "unnamed tool"].append(event)
    tools = []
    for name, calls in grouped.items():
        errors = [e for e in calls if e.status == "error"]
        latencies = [e.latency_ms for e in calls if e.latency_ms is not None]
        series = {key: {"calls": 0, "errors": 0, "latencies": []} for key in empty_buckets(start, end, unit)}
        for event in calls:
            point = series.setdefault(bucket_key(event.timestamp, unit), {"calls": 0, "errors": 0, "latencies": []})
            point["calls"] += 1
            point["errors"] += event.status == "error"
            if event.latency_ms is not None:
                point["latencies"].append(event.latency_ms)
        tools.append({
            "name": name, "calls": len(calls), "errors": len(errors),
            "success_rate": round(100 * (len(calls) - len(errors)) / len(calls), 2),
            "avg_latency_ms": average(latencies), "p50_latency_ms": percentile(latencies, 0.5),
            "p95_latency_ms": percentile(latencies, 0.95),
            "conversations": len({e.conversation_id for e in calls}),
            "users": len({e.user_id for e in calls if e.user_id}),
            "first_seen": iso(min(e.timestamp for e in calls)), "last_seen": iso(max(e.timestamp for e in calls)),
            "timeline": [{"t": iso(key), "calls": value["calls"], "errors": value["errors"],
                          "avg_latency_ms": average(value["latencies"])} for key, value in sorted(series.items())],
            "top_errors": error_groups(errors),
        })
    tools.sort(key=lambda row: (-row["calls"], row["name"]))
    total_errors = sum(row["errors"] for row in tools)
    return {
        "granularity": unit, "tools": tools,
        "total_calls": len(selected), "total_errors": total_errors,
        "error_distribution": [{"name": row["name"], "errors": row["errors"],
                                "share": round(100 * row["errors"] / total_errors, 2)}
                               for row in sorted(tools, key=lambda r: (-r["errors"], r["name"])) if row["errors"]],
    }


# ---- event log ----

def event_type(event):
    kind = (event.event_metadata or {}).get("event_type")
    if kind in ("turn", "tool_call"):
        return kind
    return "tool_call" if event.role == "tool" else "message"


def event_row(event, *, full=False):
    row = analysis.event_dict(event)
    row["session_id"] = event.source_conversation_id
    row["event_type"] = event_type(event)
    content = row["content"] or ""
    row["truncated"] = not full and len(content) > LIST_CONTENT_CHARS
    if row["truncated"]:
        row["content"] = content[:LIST_CONTENT_CHARS]
    if not full:
        row["metadata"] = {k: v for k, v in (row["metadata"] or {}).items() if k not in ("input", "output")}
    return row


def filter_events(events, *, role=None, status=None, name=None, user_id=None, conversation_id=None,
                  search=None, kind=None, metadata_key=None, metadata_value=None):
    needle = (search or "").casefold()
    selected = []
    for event in events:
        metadata = event.event_metadata or {}
        if role and event.role != role:
            continue
        if status and event.status != status:
            continue
        if name and (event.name or "") != name:
            continue
        if user_id and (event.user_id or "") != user_id:
            continue
        if conversation_id and conversation_id not in (event.conversation_id, event.source_conversation_id):
            continue
        if kind and event_type(event) != kind:
            continue
        if metadata_key and (metadata_key not in metadata or
                             (metadata_value is not None and str(metadata[metadata_key]) != metadata_value)):
            continue
        if needle and needle not in (event.content or "").casefold() and needle not in (event.name or "").casefold():
            continue
        selected.append(event)
    return selected


def paginate(rows, page, page_size):
    total = len(rows)
    pages = math.ceil(total / page_size) if total else 0
    begin = (page - 1) * page_size
    return rows[begin:begin + page_size], {"page": page, "page_size": page_size, "total": total,
                                           "total_pages": pages, "has_more": begin + page_size < total}


FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value):
    """Spreadsheet apps execute cells that start with a formula character."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def events_csv(events):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    columns = ["id", "timestamp", "session_id", "user_id", "event_type", "role", "name", "status",
               "latency_ms", "tokens", "cost_usd", "model", "content"]
    writer.writerow(columns)
    for event in events:
        row = event_row(event, full=True)
        writer.writerow([csv_cell(row[column]) for column in columns])
    return buffer.getvalue()


# ---- metadata, users, groups, search ----

def conversation_attributes(sessions, users):
    """Per conversation: session metadata and the user's traits, by key."""
    traits = {user.user_id: user.traits or {} for user in users}
    attributes = {}
    for row in sessions:
        attributes[row.conversation_id] = {
            **{key: ("user", value) for key, value in traits.get(row.user_id or "", {}).items()},
            **{key: ("user", value) for key, value in (row.user_data or {}).items() if key != "user_id"},
            **{key: ("session", value) for key, value in (row.session_metadata or {}).items()},
        }
    return attributes


def metadata_distribution(events, attributes, key=None, limit=50):
    seen = defaultdict(lambda: {"source": None, "events": 0, "conversations": set(),
                                "values": Counter(), "value_conversations": defaultdict(set)})
    for event in events:
        for item, value in (event.event_metadata or {}).items():
            if item in INTERNAL_KEYS:
                continue
            entry = seen[item]
            entry["source"] = entry["source"] or "event"
            entry["events"] += 1
            entry["conversations"].add(event.conversation_id)
            entry["values"][str(value)[:200]] += 1
            entry["value_conversations"][str(value)[:200]].add(event.conversation_id)
    active = {e.conversation_id for e in events}
    for conversation_id, values in attributes.items():
        if conversation_id not in active:
            continue
        for item, (source, value) in values.items():
            entry = seen[item]
            entry["source"] = entry["source"] or source
            if conversation_id not in entry["conversations"]:
                entry["conversations"].add(conversation_id)
                entry["values"][str(value)[:200]] += 1
                entry["value_conversations"][str(value)[:200]].add(conversation_id)
    if key is not None:
        entry = seen.get(key)
        if entry is None:
            return {"key": key, "values": []}
        return {"key": key, "source": entry["source"], "conversations": len(entry["conversations"]),
                "values": [{"value": value, "count": count,
                            "conversations": len(entry["value_conversations"][value])}
                           for value, count in entry["values"].most_common(limit)]}
    return {"keys": sorted(({"key": item, "source": entry["source"], "events": entry["events"],
                             "conversations": len(entry["conversations"]), "distinct_values": len(entry["values"]),
                             "top_values": [{"value": value, "count": count}
                                            for value, count in entry["values"].most_common(5)]}
                            for item, entry in seen.items()),
                           key=lambda row: (-row["conversations"], row["key"]))}


def problem_labels(signals):
    return sorted({analysis.RULES[s["kind"]]["title"] for s in signals})


def user_summaries(events, signals, users):
    traits = {user.user_id: user for user in users}
    grouped = defaultdict(list)
    for event in events:
        if event.user_id:
            grouped[event.user_id].append(event)
    by_conversation = defaultdict(list)
    for signal in signals:
        by_conversation[signal["conversation_id"]].append(signal)
    rows = []
    for user_id, items in grouped.items():
        conversations = {e.conversation_id for e in items}
        flagged = [s for c in conversations for s in by_conversation.get(c, [])]
        profile = traits.get(user_id)
        latest = max(items, key=lambda e: (utc(e.timestamp), e.id))
        rows.append({
            "user_id": user_id, "traits": (profile.traits if profile else {}) or {},
            "first_seen": iso(profile.first_seen) if profile else iso(min(e.timestamp for e in items)),
            "last_active": iso(latest.timestamp),
            "conversations": len(conversations), "messages": len(items),
            "operations": sum(1 for e in items if is_operation(e)),
            "errors": sum(1 for e in items if is_operation(e) and e.status == "error"),
            "problem_conversations": len({s["conversation_id"] for s in flagged}),
            "problem_labels": problem_labels(flagged),
            "latest_conversation_id": latest.conversation_id,
        })
    return rows


def group_conversations(events, signals, attributes, key):
    by_conversation = defaultdict(list)
    for event in events:
        by_conversation[event.conversation_id].append(event)
    flagged = defaultdict(list)
    for signal in signals:
        flagged[signal["conversation_id"]].append(signal)
    groups = defaultdict(lambda: {"conversations": set(), "users": set(), "messages": 0,
                                  "signals": [], "last_active": None})
    for conversation_id, items in by_conversation.items():
        values = {str(e.event_metadata[key])[:200] for e in items if key in (e.event_metadata or {})}
        if key in attributes.get(conversation_id, {}):
            values.add(str(attributes[conversation_id][key][1])[:200])
        for value in values or {None}:
            group = groups[value]
            group["conversations"].add(conversation_id)
            group["users"].update(e.user_id for e in items if e.user_id)
            group["messages"] += len(items)
            group["signals"].extend(flagged.get(conversation_id, []))
            latest = max(utc(e.timestamp) for e in items)
            group["last_active"] = max(group["last_active"] or latest, latest)
    rows = [{"value": value, "conversations": len(group["conversations"]), "users": len(group["users"]),
             "messages": group["messages"],
             "problem_conversations": len({s["conversation_id"] for s in group["signals"]}),
             "problem_labels": problem_labels(group["signals"]),
             "last_active": iso(group["last_active"])} for value, group in groups.items()]
    # A conversation with several values for the key lands in several groups.
    overlapping = sum(len(g["conversations"]) for g in groups.values()) > len(by_conversation)
    return {"key": key, "overlapping": overlapping,
            "groups": sorted(rows, key=lambda row: (row["value"] is None, -row["conversations"], row["value"] or ""))}


def snippet(text, needle, radius=80):
    index = text.casefold().find(needle)
    begin, end = max(0, index - radius), min(len(text), index + len(needle) + radius)
    return ("…" if begin else "") + text[begin:end] + ("…" if end < len(text) else "")


def search(events, query, limit=50):
    needle = query.casefold()
    matches = [e for e in events if needle in (e.content or "").casefold()]
    matches.sort(key=lambda e: (utc(e.timestamp), e.id), reverse=True)
    return {"query": query, "total": len(matches),
            "conversations": len({e.conversation_id for e in matches}),
            "results": [{"event_id": e.id, "conversation_id": e.conversation_id, "session_id": e.source_conversation_id,
                         "user_id": e.user_id, "role": e.role, "name": e.name, "timestamp": iso(e.timestamp),
                         "snippet": snippet(e.content, needle)} for e in matches[:limit]]}


# ---- routes ----

def text_filter():
    # FastAPI binds a Query object to the first parameter it is used for, so
    # every parameter needs its own.
    return Query(default=None, max_length=200)


def register(app, *, sessions, read_project, project_signals):
    """Mount the analytics routes. `read_project` enforces dashboard access;
    `project_signals` returns (events, signals) for the whole project."""

    def load(db_session, project_id, range):
        query = select(Event).where(Event.project_id == project_id)
        if range != "all":
            query = query.where(Event.timestamp >= utc_now() - timedelta(hours=RANGE_HOURS[range]))
        events = list(db_session.scalars(query.order_by(Event.timestamp, Event.id)))
        start, end = window(range, events)
        return events, start, end

    def attributes_for(db_session, project_id):
        rows = list(db_session.scalars(select(ConversationSession).where(ConversationSession.project_id == project_id)))
        users = list(db_session.scalars(select(EndUser).where(EndUser.project_id == project_id)))
        return conversation_attributes(rows, users), users

    @app.get("/api/projects/{id}/summary")
    def project_summary(request: Request, id: str, range: InsightRange = "7d"):
        with sessions() as db_session:
            read_project(request, db_session, id)
            events, start, end = load(db_session, id, range)
            return {"project_id": id, "range": range, **summary(events, start, end)}

    @app.get("/api/projects/{id}/tools")
    def project_tools(request: Request, id: str, range: InsightRange = "7d"):
        with sessions() as db_session:
            read_project(request, db_session, id)
            events, start, end = load(db_session, id, range)
            return {"project_id": id, "range": range, **tool_stats(events, start, end)}

    def event_page(request, id, range, filters, page, page_size, sort):
        with sessions() as db_session:
            read_project(request, db_session, id)
            events, start, end = load(db_session, id, range)
            rows = filter_events(analysis.in_range(events, start, end), **filters)
            rows.sort(key=lambda e: (utc(e.timestamp), e.id), reverse=sort == "newest")
            return rows, page, page_size

    def event_filters(role, status, name, user_id, conversation_id, search, event_type, metadata_key, metadata_value):
        return {"role": role, "status": status, "name": name, "user_id": user_id,
                "conversation_id": conversation_id, "search": search, "kind": event_type,
                "metadata_key": metadata_key, "metadata_value": metadata_value}


    @app.get("/api/projects/{id}/events")
    def project_events(request: Request, id: str, range: InsightRange = "7d",
                       role: Literal["user", "assistant", "tool", "system"] | None = None,
                       status: Literal["success", "error"] | None = None,
                       name: str | None = text_filter(), user_id: str | None = text_filter(),
                       conversation_id: str | None = text_filter(), search: str | None = text_filter(),
                       event_type: Literal["turn", "tool_call", "message"] | None = None,
                       metadata_key: str | None = text_filter(), metadata_value: str | None = text_filter(),
                       sort: Literal["newest", "oldest"] = "newest",
                       page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200)):
        filters = event_filters(role, status, name, user_id, conversation_id, search, event_type, metadata_key, metadata_value)
        rows, page, page_size = event_page(request, id, range, filters, page, page_size, sort)
        items, meta = paginate(rows, page, page_size)
        return {"events": [event_row(e) for e in items], **meta}

    @app.get("/api/projects/{id}/events/export")
    def export_events(request: Request, id: str, range: InsightRange = "7d",
                      role: Literal["user", "assistant", "tool", "system"] | None = None,
                      status: Literal["success", "error"] | None = None,
                      name: str | None = text_filter(), user_id: str | None = text_filter(),
                      conversation_id: str | None = text_filter(), search: str | None = text_filter(),
                      event_type: Literal["turn", "tool_call", "message"] | None = None,
                      metadata_key: str | None = text_filter(), metadata_value: str | None = text_filter()):
        filters = event_filters(role, status, name, user_id, conversation_id, search, event_type, metadata_key, metadata_value)
        rows, _, _ = event_page(request, id, range, filters, 1, 1, "newest")
        return Response(events_csv(rows[:50_000]), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="tervik-events-{range}.csv"'})

    @app.get("/api/projects/{id}/events/{event_id}")
    def project_event(request: Request, id: str, event_id: str):
        with sessions() as db_session:
            read_project(request, db_session, id)
            event = db_session.get(Event, (id, event_id))
            if event is None:
                raise HTTPException(404, "Event not found")
            related = list(db_session.scalars(select(Event).where(
                Event.project_id == id, Event.conversation_id == event.conversation_id)))
            capture_id = (event.event_metadata or {}).get("capture_event_id")
            pair = [e for e in related if e.id != event.id and capture_id and
                    (e.event_metadata or {}).get("capture_event_id") == capture_id]
            parent = next((e for e in related if event.parent_span_id and e.span_id == event.parent_span_id
                           and e.role != "user"), None)
            span = event.span_id or next((e.span_id for e in pair if e.span_id), None)
            children = sorted((e for e in related if span and e.parent_span_id == span),
                              key=lambda e: (utc(e.timestamp), e.id))
            session_row = db_session.get(ConversationSession, (id, event.source_conversation_id))
            return {"event": event_row(event, full=True),
                    "pair": [event_row(e, full=True) for e in pair],
                    "parent": event_row(parent) if parent else None,
                    "children": [event_row(e) for e in children],
                    "session": None if session_row is None else {
                        "session_id": session_row.id, "user_id": session_row.user_id,
                        "user_data": session_row.user_data, "metadata": session_row.session_metadata,
                        "client_config": session_row.client_config, "started_at": iso(session_row.started_at)}}

    @app.get("/api/projects/{id}/errors")
    def project_errors(request: Request, id: str, range: InsightRange = "7d",
                       name: str | None = text_filter(), search: str | None = text_filter(),
                       page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200)):
        filters = event_filters(None, "error", name, None, None, search, None, None, None)
        rows, page, page_size = event_page(request, id, range, filters, page, page_size, "newest")
        by_name = Counter(e.name or ("agent" if e.role == "assistant" else e.role) for e in rows)
        items, meta = paginate(rows, page, page_size)
        return {"errors": [event_row(e) for e in items], **meta,
                "by_name": [{"name": key, "count": count} for key, count in by_name.most_common()],
                "top_messages": error_groups(rows, limit=10)}

    @app.get("/api/projects/{id}/metadata")
    def project_metadata(request: Request, id: str, range: InsightRange = "7d", key: str | None = text_filter()):
        with sessions() as db_session:
            read_project(request, db_session, id)
            events, start, end = load(db_session, id, range)
            attributes, _ = attributes_for(db_session, id)
            return {"project_id": id, "range": range,
                    **metadata_distribution(analysis.in_range(events, start, end), attributes, key)}

    @app.get("/api/projects/{id}/users")
    def project_users(request: Request, id: str, range: InsightRange = "7d", search: str | None = text_filter(),
                      sort: Literal["last_active", "conversations", "problems"] = "last_active",
                      page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200)):
        with sessions() as db_session:
            read_project(request, db_session, id)
            all_events, signals = project_signals(db_session, id)
            start, end = window(range, all_events)
            _, users = attributes_for(db_session, id)
            rows = user_summaries(analysis.in_range(all_events, start, end),
                                  analysis.signals_in_range(signals, start, end), users)
            if search:
                needle = search.casefold()
                rows = [row for row in rows if needle in row["user_id"].casefold() or
                        any(needle in str(value).casefold() for value in row["traits"].values())]
            order = {"last_active": lambda r: (r["last_active"], r["user_id"]),
                     "conversations": lambda r: (r["conversations"], r["last_active"]),
                     "problems": lambda r: (r["problem_conversations"], r["last_active"])}[sort]
            rows.sort(key=order, reverse=True)
            items, meta = paginate(rows, page, page_size)
            return {"users": items, **meta}

    @app.get("/api/projects/{id}/groups")
    def project_groups(request: Request, id: str, key: str = Query(min_length=1, max_length=100),
                       range: InsightRange = "7d"):
        with sessions() as db_session:
            read_project(request, db_session, id)
            all_events, signals = project_signals(db_session, id)
            start, end = window(range, all_events)
            attributes, _ = attributes_for(db_session, id)
            return {"project_id": id, "range": range,
                    **group_conversations(analysis.in_range(all_events, start, end),
                                          analysis.signals_in_range(signals, start, end), attributes, key)}

    @app.get("/api/projects/{id}/search")
    def project_search(request: Request, id: str, q: str = Query(min_length=2, max_length=200),
                       range: InsightRange = "30d", limit: int = Query(default=50, ge=1, le=200)):
        with sessions() as db_session:
            read_project(request, db_session, id)
            events, start, end = load(db_session, id, range)
            return search(analysis.in_range(events, start, end), q, limit)
