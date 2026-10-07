"""Evidence-backed heuristics, deliberately not a machine learning classifier."""
from collections import defaultdict
from datetime import timedelta
import re
from uuid import NAMESPACE_URL, uuid5
from .db import iso, utc

ANALYSIS_MODE = "rule_based"
DETECTOR_VERSION = "5.0.0"
RULE_VERSIONS = {
    "correction": "5.0.0",
    "frustration": "5.0.0",
    "repetition": "5.0.0",
    "tool_error": "5.0.0",
    "tool_timeout": "5.0.0",
    "unresolved": "5.0.0",
    "unsupported_claim": "5.0.0",
    "rule_violation": "5.0.0",
}
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
    "tool_timeout": {
        "title": "Tool calls time out",
        "description": "A tool event reports an explicit timeout. Evidence comes directly from the recorded tool result.",
        "severity": "high",
        "suggested_fix": "Inspect the timed-out tool, add a deadline and fallback, and test slow-dependency behavior.",
    },
    "unresolved": {
        "title": "Users say the issue is not resolved",
        "description": "A user message explicitly states the problem persists. This is recorded text, not inferred abandonment.",
        "severity": "high",
        "suggested_fix": "Read the unresolved request, reproduce the remaining problem, and confirm the fix with the user.",
    },
    "unsupported_claim": {
        "title": "Agent claims an action without tool evidence",
        "description": "An assistant message claims a completed action with no supporting successful tool call in the same turn. Saying an action was done does not prove it.",
        "severity": "high",
        "suggested_fix": "Check whether any tool actually performed the claimed action. Require tool confirmation before the agent reports completion.",
    },
    "rule_violation": {
        "title": "A behavior rule was violated",
        "description": "A customer-defined behavior rule matched recorded telemetry. Evidence cites the rule and the matching record.",
        "severity": "high",
        "suggested_fix": "Review the cited rule and evidence, then adjust the agent's instructions or required tooling.",
    },
}
CORRECTION = re.compile(r"\b(?:that(?:'s| is) (?:wrong|incorrect|not what i)|you misunderstood|i (?:asked for|meant)|no[,!]?\s+(?:i meant|that(?:'s| is) not)|not what i (?:asked|meant)|the answer is (?:wrong|incorrect))\b", re.I)
FRUSTRATION = re.compile(r"\b(?:frustrat(?:ing|ed)|useless|this (?:doesn't|does not) work|this is not working|still (?:doesn't|does not) work|stop (?:ignoring|repeating)|waste of (?:my )?time|you keep (?:ignoring|getting it wrong))\b", re.I)
TIMEOUT = re.compile(r"\b(?:timed?\s?out|timeout|deadline\s+exceeded|ETIMEDOUT|exceeded.*deadline)\b", re.I)
UNRESOLVED = re.compile(r"\b(?:that (?:didn't|did not|didnt) work|still (?:broken|failing|not working)|you (?:didn't|did not|didnt) (?:fix|answer|resolve)|not (?:fixed|resolved|answered)|same problem|still (?:having|have) (?:this|the) (?:issue|problem)|issue (?:persists|remains)|(?:didn'?t|did not|didnt) (?:help|solve))\b", re.I)
ACTION_CLAIM = re.compile(r"\b(?:i['’]?(?:ve| have) (?:sent|booked|created|deleted|updated|fixed|deployed|emailed|scheduled|cancelled|refunded|processed)|sent the|booking is confirmed|refund(?:ed|s)? (?:issued|processed)|order (?:is |has been )?(?:placed|cancelled)|email (?:has been )?sent|i['’]?ll have (?:sent|booked)|all done|taken care of)\b", re.I)


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


def analyze(events, rules=None):
    """Deterministic, evidence-backed detectors.

    Every signal cites recorded message/span ids, carries the detector and
    rule versions, and abstains (`insufficient evidence`) instead of guessing:
    silence never proves abandonment, and a claimed action without tool
    evidence is flagged rather than assumed delivered.
    """
    signals = []
    seen = defaultdict(set)
    ordered = sorted(events, key=lambda e: (utc(e.timestamp), e.id))

    def emit(event, kind, reason, tool_name=""):
        signals.append({
            "id": str(uuid5(NAMESPACE_URL, f"tervik:{event.project_id}:{event.id}:{kind}")),
            "event_id": event.id, "conversation_id": event.conversation_id,
            "kind": kind, "reason": reason, "severity": RULES[kind]["severity"],
            "detector_version": DETECTOR_VERSION, "rule_version": RULE_VERSIONS[kind],
            "cluster_id": cluster_id(event.project_id, kind, tool_name), "tool_name": tool_name,
            "event": event,
        })

    successful_tools = defaultdict(list)
    for event in ordered:
        if event.role == "tool" and event.status != "error":
            successful_tools[event.trace_id or ""].append(event)

    for event in ordered:
        found = []
        if event.role == "user":
            content = event.content.replace("’", "'")
            for kind, regex in (("correction", CORRECTION), ("frustration", FRUSTRATION),
                                ("unresolved", UNRESOLVED)):
                match = regex.search(content)
                if match:
                    found.append((kind, f'User message contains the explicit phrase "{match.group(0)}".'))
            normalized = re.sub(r"\W+", " ", content.casefold()).strip()
            if len(normalized) >= 8 and normalized in seen[event.conversation_id]:
                found.append(("repetition", "This normalized user request appeared earlier in the same conversation."))
            seen[event.conversation_id].add(normalized)
        elif event.role == "tool" and event.status == "error":
            text = f"{event.name or ''} {event.content}".replace("’", "'")
            if TIMEOUT.search(text):
                found.append(("tool_timeout", f'Tool "{event.name or "unnamed tool"}" explicitly reported a timeout.'))
            else:
                found.append(("tool_error", f'Tool "{event.name or "unnamed tool"}" explicitly reported status=error.'))
        elif event.role == "assistant":
            content = event.content.replace("’", "'")
            match = ACTION_CLAIM.search(content)
            if match:
                outcome = check_claim_support(event, ordered, successful_tools)
                if outcome == "unsupported":
                    found.append(("unsupported_claim",
                        f'Assistant claims "{match.group(0)}" with no supporting successful tool call in the same turn.'))
                # "unattributable" abstains: the claim cannot be tied to a turn,
                # so silence about evidence proves nothing either way.
        for kind, reason in found:
            tool_name = (event.name or "unnamed tool") if kind in ("tool_error", "tool_timeout") else ""
            emit(event, kind, reason, tool_name)

    for rule in rules or []:
        for event, reason in check_rule(rule, ordered):
            emit(event, "rule_violation", reason, "")
    return signals


def check_claim_support(event, ordered, successful_tools=None):
    """Return 'supported', 'unsupported', or 'unattributable' for a claim.

    A claim is supported by a successful tool call in the same trace before
    the claim. Without trace linkage, a conversation with no tool activity
    at all is unsupported; tool activity that cannot be attributed to this
    turn abstains as insufficient evidence.
    """
    trace = event.trace_id
    if trace:
        prior = [e for e in (successful_tools or {}).get(trace, [])
                 if (utc(e.timestamp), e.id) <= (utc(event.timestamp), event.id)]
        return "supported" if prior else "unsupported"
    tools = [e for e in ordered if e.role == "tool" and e.status != "error"
             and e.conversation_id == event.conversation_id
             and (utc(e.timestamp), e.id) <= (utc(event.timestamp), event.id)]
    if not tools:
        return "unsupported"
    return "unattributable"


def check_rule(rule, ordered):
    """Apply one customer behavior rule. Yields (event, reason) pairs."""
    kind = (rule.get("kind") if isinstance(rule, dict) else getattr(rule, "kind", None)) or ""
    name = (rule.get("name") if isinstance(rule, dict) else getattr(rule, "name", "")) or "rule"
    if kind == "forbidden_phrase":
        pattern = (rule.get("pattern") if isinstance(rule, dict) else getattr(rule, "pattern", "")) or ""
        try:
            regex = re.compile(pattern, re.I)
        except re.error:
            return
        for event in ordered:
            if event.role == "assistant" and event.content and regex.search(event.content):
                yield event, f'Assistant message matches behavior rule "{name}".'
    elif kind == "required_tool":
        tool = (rule.get("tool") if isinstance(rule, dict) else getattr(rule, "tool", "")) or ""
        if not tool:
            return
        by_conversation = defaultdict(list)
        for event in ordered:
            by_conversation[event.conversation_id].append(event)
        for conversation_id, messages in by_conversation.items():
            supported = any(e.role == "tool" and e.status != "error" and (e.name or "") == tool
                            for e in messages)
            if not supported:
                assistants = [e for e in messages if e.role == "assistant"]
                if assistants:
                    yield assistants[-1], (f'Behavior rule "{name}" requires tool "{tool}", '
                                           f'which has no successful call in this conversation.')


def public_signal(signal):
    return {key: signal[key] for key in ("id", "event_id", "conversation_id", "kind", "reason", "severity",
                                         "detector_version", "rule_version")}


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
            (f' · {evidence[0]["tool_name"]}' if kind in ("tool_error", "tool_timeout") else ""),
            "description": rule["description"], "severity": rule["severity"], "kind": kind,
            "detector_version": DETECTOR_VERSION, "rule_version": RULE_VERSIONS[kind],
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
