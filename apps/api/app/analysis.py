"""Evidence-backed heuristics, deliberately not a machine learning classifier."""
from collections import defaultdict
from datetime import timedelta
import re
from uuid import NAMESPACE_URL, uuid5
from .db import iso, utc

ANALYSIS_MODE = "rule_based"
RULES = {
    "correction": {
        "title": "Users are correcting the agent",
        "description": "Explicit correction phrases appear in user messages. Review the original conversation before deciding whether the response was wrong.",
        "severity": "medium",
        "suggested_fix": "Review the cited turns, identify the misunderstood requirement, and add a regression example before changing the agent's instructions.",
    },
    "frustration": {
        "title": "Users express frustration",
        "description": "User messages include explicit frustration language. This is a text heuristic, not a sentiment or churn prediction.",
        "severity": "high",
        "suggested_fix": "Review the preceding responses and tool calls. Reproduce the obstacle, improve recovery, and test the same request again.",
    },
    "repetition": {
        "title": "Users repeat their requests",
        "description": "The same normalized user request appears more than once in a conversation. Repetition can be intentional and requires review.",
        "severity": "medium",
        "suggested_fix": "Check whether the earlier request was answered. Add an evaluation for repeated requests and ask for clarification when necessary.",
    },
    "tool_error": {
        "title": "Tool calls return errors",
        "description": "A tool event reports an explicit error status. Evidence comes directly from the recorded tool result.",
        "severity": "high",
        "suggested_fix": "Inspect the recorded tool error, fix the underlying failure, and test the agent's retry and fallback behavior.",
    },
}
CORRECTION = re.compile(r"\b(?:that(?:'s| is) (?:wrong|incorrect|not what i)|you misunderstood|i (?:asked for|meant)|no[,!]?\s+(?:i meant|that(?:'s| is) not)|not what i (?:asked|meant)|the answer is (?:wrong|incorrect))\b", re.I)
FRUSTRATION = re.compile(r"\b(?:frustrat(?:ing|ed)|useless|this (?:doesn't|does not) work|this is not working|still (?:doesn't|does not) work|stop (?:ignoring|repeating)|waste of (?:my )?time|you keep (?:ignoring|getting it wrong))\b", re.I)


def cluster_id(project_id, kind, tool_name=""):
    return str(uuid5(NAMESPACE_URL, f"tervik:{project_id}:{kind}:{tool_name}"))


def event_dict(event):
    return {
        "id": event.id, "conversation_id": event.conversation_id, "user_id": event.user_id,
        "role": event.role, "content": event.content, "timestamp": iso(event.timestamp),
        "trace_id": event.trace_id, "span_id": event.span_id, "parent_span_id": event.parent_span_id,
        "name": event.name, "status": event.status, "latency_ms": event.latency_ms,
        "tokens": event.tokens, "cost_usd": event.cost_usd, "model": event.model,
        "metadata": event.event_metadata,
    }


def analyze(events):
    signals = []
    seen = defaultdict(set)
    for event in sorted(events, key=lambda e: (utc(e.timestamp), e.id)):
        found = []
        if event.role == "user":
            content = event.content.replace("’", "'")
            for kind, regex in (("correction", CORRECTION), ("frustration", FRUSTRATION)):
                match = regex.search(content)
                if match:
                    found.append((kind, f'User message contains the explicit phrase "{match.group(0)}".'))
            normalized = re.sub(r"\W+", " ", content.casefold()).strip()
            if len(normalized) >= 8 and normalized in seen[event.conversation_id]:
                found.append(("repetition", "This normalized user request appeared earlier in the same conversation."))
            seen[event.conversation_id].add(normalized)
        elif event.role == "tool" and event.status == "error":
            found.append(("tool_error", f'Tool "{event.name or "unnamed tool"}" explicitly reported status=error.'))
        for kind, reason in found:
            tool_name = (event.name or "unnamed tool") if kind == "tool_error" else ""
            signals.append({
                "id": str(uuid5(NAMESPACE_URL, f"tervik:{event.project_id}:{event.id}:{kind}")),
                "event_id": event.id, "conversation_id": event.conversation_id,
                "kind": kind, "reason": reason, "severity": RULES[kind]["severity"],
                "cluster_id": cluster_id(event.project_id, kind, tool_name), "tool_name": tool_name,
                "event": event,
            })
    return signals


def public_signal(signal):
    return {key: signal[key] for key in ("id", "event_id", "conversation_id", "kind", "reason", "severity")}


def summary(events, signals):
    ordered = sorted(events, key=lambda e: (utc(e.timestamp), e.id))
    first, last = ordered[0], ordered[-1]
    user_events = [e for e in ordered if e.role == "user"]
    models = [e.model for e in ordered if e.model]
    users = [e.user_id for e in ordered if e.user_id]
    return {
        "id": first.conversation_id, "project_id": first.project_id,
        "user_id": users[0] if users else None,
        "started_at": iso(first.timestamp), "last_at": iso(last.timestamp),
        "message_count": len(ordered), "latency_ms": round(sum(e.latency_ms or 0 for e in ordered), 2),
        "status": "flagged" if signals else "healthy",
        "tags": sorted({s["kind"] for s in signals}),
        "preview": (user_events[0].content if user_events else first.content)[:180],
        "model": models[-1] if models else None,
        "cost_usd": round(sum(e.cost_usd or 0 for e in ordered), 8),
    }


def conversation_summaries(events, signals):
    groups, grouped_signals = defaultdict(list), defaultdict(list)
    for event in events:
        groups[event.conversation_id].append(event)
    for signal in signals:
        grouped_signals[signal["conversation_id"]].append(signal)
    return sorted((summary(value, grouped_signals[key]) for key, value in groups.items()),
                  key=lambda s: (s["last_at"], s["id"]), reverse=True)


def in_range(events, start, end):
    return [event for event in events if start <= utc(event.timestamp) <= end]


def signals_in_range(signals, start, end):
    return [signal for signal in signals if start <= utc(signal["event"].timestamp) <= end]


def clusters(project_id, all_events, all_signals, states, start, end):
    current_events = in_range(all_events, start, end)
    denominator = len({e.conversation_id for e in current_events})
    current = defaultdict(list)
    previous = defaultdict(set)
    previous_start = start - (end - start)
    for signal in all_signals:
        timestamp = utc(signal["event"].timestamp)
        if start <= timestamp <= end:
            current[signal["cluster_id"]].append(signal)
        elif previous_start <= timestamp < start:
            previous[signal["cluster_id"]].add(signal["conversation_id"])
    rows = []
    for id, evidence in current.items():
        kind = evidence[0]["kind"]
        rule = RULES[kind]
        affected_conversations = {s["conversation_id"] for s in evidence}
        count = len(affected_conversations)
        prior = len(previous[id])
        historical = [s for s in all_signals if s["cluster_id"] == id and utc(s["event"].timestamp) <= end]
        rows.append({
            "id": id, "project_id": project_id, "title": rule["title"] +
            (f' · {evidence[0]["tool_name"]}' if kind == "tool_error" else ""),
            "description": rule["description"], "severity": rule["severity"], "kind": kind,
            "status": states.get(id, "open"), "count": count,
            "affected_users": len({e.user_id for e in current_events
                                   if e.conversation_id in affected_conversations and e.user_id}),
            "share": round(100 * count / denominator, 2) if denominator else 0,
            "trend": round(100 * (count - prior) / prior, 2) if prior else (100 if count else 0),
            "created_at": iso(min(s["event"].timestamp for s in historical)),
            "last_seen": iso(max(s["event"].timestamp for s in evidence)),
            "suggested_fix": rule["suggested_fix"],
        })
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(rows, key=lambda c: (-c["count"], severity_order[c["severity"]], c["title"]))


def overview(project, events, signals, cluster_rows, start, end):
    selected = in_range(events, start, end)
    selected_signals = signals_in_range(signals, start, end)
    summaries = conversation_summaries(selected, selected_signals)
    failed = {s["conversation_id"] for s in selected_signals}
    affected = {e.user_id for e in selected if e.conversation_id in failed and e.user_id}
    latencies = [e.latency_ms for e in selected if e.latency_ms is not None]
    buckets = {}
    day = start.date()
    while day <= end.date():
        buckets[day.isoformat()] = {"date": day.isoformat(), "conversations": set(), "failures": set()}
        day += timedelta(days=1)
    for event in selected:
        buckets[utc(event.timestamp).date().isoformat()]["conversations"].add(event.conversation_id)
    for signal in selected_signals:
        buckets[utc(signal["event"].timestamp).date().isoformat()]["failures"].add(signal["conversation_id"])
    return {
        "project": project,
        "metrics": {
            "conversations": len(summaries), "messages": len(selected),
            "failure_rate": round(100 * len(failed) / len(summaries), 2) if summaries else 0,
            "affected_users": len(affected),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
            "cost_usd": round(sum(e.cost_usd or 0 for e in selected), 8),
        },
        "trend": [{"date": bucket["date"], "conversations": len(bucket["conversations"]),
                   "failures": len(bucket["failures"])} for bucket in buckets.values()],
        "top_clusters": cluster_rows[:5], "recent_conversations": summaries[:8],
        "analysis_mode": ANALYSIS_MODE,
    }


def spans(events):
    found = {}
    for event in sorted(events, key=lambda e: (utc(e.timestamp), e.id)):
        if not event.span_id:
            continue
        found[event.span_id] = {
            "id": event.span_id, "parent_id": event.parent_span_id,
            "name": event.name or event.role, "kind": event.role, "status": event.status,
            "duration_ms": event.latency_ms or 0,
            "input": event.event_metadata.get("input"),
            "output": event.event_metadata.get("output", event.content),
        }
    return list(found.values())
