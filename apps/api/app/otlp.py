"""Phase 2 OTLP normalization.

Accepts OTLP TracesData JSON (resourceSpans) and converts spans to the
canonical event shape. Span identity (trace/span/parent) is preserved, so
nested and out-of-order spans keep their relationships.
"""
from datetime import datetime, timezone
from uuid import uuid4

STATUS_ERROR = 2


def _attributes(span: dict) -> dict:
    values = {}
    for item in span.get("attributes", []) or []:
        key = item.get("key", "")
        val = item.get("value", {}) or {}
        for field in ("stringValue", "boolValue", "intValue"):
            if field in val:
                values[key] = val[field]
                break
        if "doubleValue" in val:
            values[key] = val["doubleValue"]
        elif "arrayValue" in val and key not in values:
            raw = val["arrayValue"].get("values", [])
            collected = []
            for entry in raw:
                for field in ("stringValue", "boolValue", "intValue", "doubleValue"):
                    if field in entry:
                        collected.append(entry[field])
                        break
            values[key] = collected
    flat = dict(span.get("attributes_flat", {}) or {})
    values.update(flat)
    return values


def _content(name: str, attrs: dict) -> str:
    for key in ("gen_ai.completion.0.content", "gen_ai.prompt.0.content",
                "exception.message", "status.message", "tervik.content"):
        value = attrs.get(key)
        if isinstance(value, str) and value.strip():
            return value[:32_000]
        if isinstance(value, list) and value and isinstance(value[0], str):
            return str(value[0])[:32_000]
    return name or "span"


def _role(attrs: dict, kind: int | None) -> str:
    hint = str(attrs.get("tervik.role", "")).lower()
    if hint in ("user", "assistant", "tool", "system"):
        return hint
    # OTLP kind 3 = CLIENT (often a tool call), 2 = SERVER.
    if kind == 3 or attrs.get("db.system") or attrs.get("http.url") or attrs.get("tool.name"):
        return "tool"
    return "assistant"


def normalize_otlp_traces(body: dict, *, default_conversation: str | None = None) -> list[dict]:
    """Convert OTLP JSON to canonical event dicts ready for validation."""
    events = []
    for resource in body.get("resourceSpans", []) or []:
        for scope in resource.get("scopeSpans", []) or []:
            for span in scope.get("spans", []) or []:
                attrs = _attributes(span)
                trace_id = span.get("traceId", "")
                span_id = span.get("spanId", "")
                parent = span.get("parentSpanId") or None
                name = span.get("name", "span")
                start_ns = int(span.get("startTimeUnixNano") or 0)
                end_ns = int(span.get("endTimeUnixNano") or 0)
                latency = round((end_ns - start_ns) / 1e6, 3) if end_ns > start_ns else None
                status = span.get("status", {}) or {}
                is_error = status.get("code") == STATUS_ERROR
                for event in span.get("events", []) or []:
                    if (event.get("name") or "").lower() == "exception" and not is_error:
                        is_error = True
                conversation = (attrs.get("tervik.conversation.id") or attrs.get("conversation_id")
                                or attrs.get("session.id") or default_conversation or trace_id or str(uuid4()))
                timestamp = datetime.now(timezone.utc)
                if end_ns:
                    timestamp = datetime.fromtimestamp(end_ns / 1e9, tz=timezone.utc)
                events.append({
                    "id": f"otlp-{trace_id}-{span_id}" if trace_id and span_id else str(uuid4()),
                    "conversation_id": str(conversation),
                    "user_id": attrs.get("enduser.id") or attrs.get("user.id"),
                    "role": _role(attrs, span.get("kind")),
                    "content": _content(name, attrs),
                    "timestamp": timestamp.isoformat(),
                    "trace_id": trace_id or None,
                    "span_id": span_id or None,
                    "parent_span_id": parent,
                    "name": attrs.get("tool.name") or name,
                    "status": "error" if is_error else "success",
                    "latency_ms": latency,
                    "metadata": {
                        "otel.kind": span.get("kind"),
                        "otel.status": status.get("code"),
                        "gen_ai.system": attrs.get("gen_ai.system"),
                        "gen_ai.request.model": attrs.get("gen_ai.request.model"),
                    },
                })
    return events
