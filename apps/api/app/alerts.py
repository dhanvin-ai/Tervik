"""Phase 7 alerts: threshold/trend evaluation, summaries, deliveries.

Rules fire at most once per cooldown window per rule (dedup key), failed
deliveries retry with bounded backoff, and resolution is tracked when the
condition clears. Channel secrets live on the rule and are never returned
by the API or stored on deliveries (only a hash).
"""
from collections import Counter
import hashlib
import json
import logging
import smtplib
import urllib.request
from datetime import timedelta
from email.message import EmailMessage
from uuid import uuid4

from sqlalchemy import func, select

from .db import (AlertDelivery, AlertRule, AnalyzedConversation, BehaviorRule, Classification, Event, Project, utc,
                 utc_now)

logger = logging.getLogger(__name__)

MAX_DELIVERY_ATTEMPTS = 8
DELIVERY_BACKOFF = [60, 300, 1800, 7200, 21600, 86400, 172800, 345600]


def hash_target(target: str) -> str:
    return hashlib.sha256(target.encode()).hexdigest()[:16]


CHANNEL_TYPES = ("webhook", "email", "slack")
METRIC_NOUNS = {None: "flagged conversations", "problems": "flagged conversations",
                "intent": "conversations with this intent", "violation": "conversations that broke this policy",
                "tool_errors": "failed tool calls", "error_rate": "% of operations failed",
                "conversations": "conversations"}
CONTEXT_ROWS = 5


def rule_channels(rule) -> list:
    channels = rule.channels or []
    return [c for c in channels if isinstance(c, dict) and c.get("type") in CHANNEL_TYPES]


def public_rule(rule):
    return {"id": rule.id, "project_id": rule.project_id, "name": rule.name,
            "kind": rule.kind, "signal_kind": rule.signal_kind,
            "metric": rule.metric, "target": rule.target,
            "threshold": rule.threshold, "window_hours": rule.window_hours,
            "min_samples": rule.min_samples, "cooldown_hours": rule.cooldown_hours,
            "channels": [{"type": c.get("type"), "configured": bool(c.get("target"))}
                         for c in rule_channels(rule)],
            "enabled": rule.enabled, "state": rule.state,
            "last_fired_at": rule.last_fired_at.isoformat().replace("+00:00", "Z") if rule.last_fired_at else None,
            "resolved_at": rule.resolved_at.isoformat().replace("+00:00", "Z") if rule.resolved_at else None}


def public_delivery(delivery):
    return {"id": delivery.id, "rule_id": delivery.rule_id, "state": delivery.state,
            "attempts": delivery.attempts, "channel_type": delivery.channel_type,
            "title": delivery.title, "error_code": delivery.error_code,
            "sent_at": delivery.sent_at.isoformat().replace("+00:00", "Z") if delivery.sent_at else None,
            "created_at": delivery.created_at.isoformat().replace("+00:00", "Z")}


def _window_events(session, project_id, start, end):
    return [e for e in session.scalars(select(Event).where(
        Event.project_id == project_id, Event.timestamp >= start).order_by(Event.timestamp, Event.id))
        if utc(e.timestamp) <= end]


def _signals(session, project_id, events):
    from . import analysis
    from .classify import policy_signals
    rules = list(session.scalars(select(BehaviorRule).where(
        BehaviorRule.project_id == project_id, BehaviorRule.enabled == True)))  # noqa: E712
    return analysis.analyze(events, rules) + policy_signals(session, project_id, events)


def _flagged_counts(session, project_id, kind, start, end):
    in_window = _window_events(session, project_id, start, end)
    signals = [s for s in _signals(session, project_id, in_window) if not kind or s["kind"] == kind]
    flagged = {s["conversation_id"] for s in signals}
    total = {e.conversation_id for e in in_window}
    return len(flagged), len(total)


def _examples(events_by_conversation, conversation_ids):
    """Up to five recent conversations behind a number, for the alert body."""
    rows = []
    for conversation_id in conversation_ids:
        events = events_by_conversation.get(conversation_id) or []
        if not events:
            continue
        last = max(events, key=lambda e: (utc(e.timestamp), e.id))
        first_user = next((e for e in events if e.role == "user" and e.content), None)
        text = " ".join(((first_user or last).content or "").split())[:140]
        rows.append((utc(last.timestamp), f"- {last.source_conversation_id or conversation_id}"
                     f"{f' ({last.user_id})' if last.user_id else ''}: {text}"))
    return [line for _, line in sorted(rows, reverse=True)[:CONTEXT_ROWS]]


def measure(session, rule, start, end):
    """(current, total, examples) for the rule's metric over [start, end]."""
    events = _window_events(session, rule.project_id, start, end)
    by_conversation = {}
    for event in events:
        by_conversation.setdefault(event.conversation_id, []).append(event)
    metric = rule.metric or "problems"
    if metric == "problems":
        signals = [s for s in _signals(session, rule.project_id, events)
                   if not rule.signal_kind or s["kind"] == rule.signal_kind]
        flagged = {s["conversation_id"] for s in signals}
        return len(flagged), len(by_conversation), _examples(by_conversation, flagged)
    if metric in ("intent", "violation"):
        rows = session.scalars(select(Classification).where(
            Classification.project_id == rule.project_id, Classification.target_id == rule.target,
            Classification.kind == ("intent" if metric == "intent" else "policy"),
            Classification.occurred_at >= start)).all()
        matched = {r.conversation_id for r in rows if utc(r.occurred_at) <= end}
        analyzed = session.execute(select(func.count()).select_from(AnalyzedConversation).where(
            AnalyzedConversation.project_id == rule.project_id, AnalyzedConversation.status == "done",
            AnalyzedConversation.last_event_at >= start)).scalar_one()
        return len(matched), analyzed, _examples(by_conversation, matched)
    operations = [e for e in events if e.role in ("assistant", "tool")]
    if metric == "tool_errors":
        tools = [e for e in operations if e.role == "tool" and (not rule.target or e.name == rule.target)]
        failed = [e for e in tools if e.status == "error"]
        return len(failed), len(tools), _examples(by_conversation, {e.conversation_id for e in failed})
    if metric == "error_rate":
        failed = [e for e in operations if e.status == "error"]
        rate = round(100 * len(failed) / len(operations), 2) if operations else 0
        return rate, len(operations), _examples(by_conversation, {e.conversation_id for e in failed})
    if metric == "conversations":
        return len(by_conversation), len(by_conversation), []
    raise ValueError("unknown_metric")


def target_label(session, rule):
    from .db import Intent, Policy
    if rule.metric == "intent" and rule.target:
        intent = session.get(Intent, rule.target)
        return intent.name if intent else None
    if rule.metric == "violation" and rule.target:
        policy = session.get(Policy, rule.target)
        return policy.title if policy else None
    return rule.target if rule.metric == "tool_errors" else None


def describe(rule, current, total, examples, dashboard_url="", label=None):
    noun = METRIC_NOUNS.get(rule.metric, "matches")
    subject = f" ({label})" if label else ""
    lines = [f"{current}{'' if rule.metric == 'error_rate' else ' '}{noun}{subject} in the last "
             f"{rule.window_hours} hours (out of {total})."]
    if examples:
        lines += ["", "Recent examples:", *examples]
    if dashboard_url:
        lines += ["", f"Open Tervik: {dashboard_url.rstrip('/')}/#overview"]
    return "\n".join(lines)


def evaluate_rule(session, rule, now=None, settings=None):
    """Check one rule. Returns (fired, detail). Creates queued deliveries."""
    now = now or utc_now()
    window = timedelta(hours=rule.window_hours or 24)
    dashboard_url = getattr(settings, "dashboard_url", "")
    if rule.kind == "summary":
        bucket = now.strftime("%Y-%m-%d")
        project = session.get(Project, rule.project_id)
        if rule.metric == "suggested_intents":
            title, body = intent_summary(session, project, now, dashboard_url)
            if body is None:
                return False, {"reason": "no_new_intents"}
        else:
            title, body = daily_summary(session, project, now, dashboard_url)
        return _fire(session, rule, bucket, title, body, now)
    current, total, examples = measure(session, rule, now - window, now)
    if total < (rule.min_samples or 0):
        _resolve(session, rule, now)
        return False, {"reason": "below_min_samples", "flagged": current, "total": total}
    if rule.kind == "threshold":
        if current < rule.threshold:
            _resolve(session, rule, now)
            return False, {"flagged": current, "total": total}
        detail = {"flagged": current, "total": total, "threshold": rule.threshold}
    elif rule.kind == "trend":
        prior, _, _ = measure(session, rule, now - 2 * window, now - window)
        if prior == 0:
            if current == 0:
                _resolve(session, rule, now)
                return False, {"flagged": current, "prior": prior}
            change = 100.0 if current else 0.0
        else:
            change = 100.0 * (current - prior) / prior
        if change < rule.threshold:
            _resolve(session, rule, now)
            return False, {"flagged": current, "prior": prior, "change": round(change, 1)}
        detail = {"flagged": current, "prior": prior, "change": round(change, 1)}
    else:
        return False, {"reason": "unknown_kind"}
    bucket = now.strftime("%Y-%m-%d-%H")
    noun = METRIC_NOUNS.get(rule.metric, "matches")
    title = f'{rule.name}: {current}{"" if rule.metric == "error_rate" else " "}{noun}'
    body = describe(rule, current, total, examples, dashboard_url, target_label(session, rule))
    if rule.kind == "trend":
        body = f'Up {detail["change"]}% from {detail["prior"]} in the previous {rule.window_hours} hours.\n' + body
    return _fire(session, rule, bucket, title, body, now)


def _fire(session, rule, bucket, title, body, now):
    last = utc(rule.last_fired_at) if rule.last_fired_at else None
    if last and last + timedelta(hours=rule.cooldown_hours or 24) > now:
        return False, {"reason": "cooldown"}
    dedup = f"{rule.id}:{bucket}"
    existing = session.scalars(select(AlertDelivery).where(
        AlertDelivery.dedup_key == dedup)).first()
    if existing is not None:
        return False, {"reason": "duplicate"}
    rule.state = "firing"
    rule.last_fired_at = now
    rule.resolved_at = None
    for index, channel in enumerate(rule_channels(rule)):
        session.add(AlertDelivery(
            id=str(uuid4()), rule_id=rule.id, project_id=rule.project_id,
            dedup_key=f"{dedup}:{index}", state="queued", channel_type=channel["type"],
            target_hash=hash_target(channel.get("target", "")),
            title=title, body=body))
    session.flush()
    return True, {"deliveries": len(rule_channels(rule))}


def _resolve(session, rule, now):
    if rule.state == "firing":
        rule.state = "ok"
        rule.resolved_at = now


def daily_summary(session, project, now, dashboard_url=""):
    """Yesterday at a glance: volume, reliability, top problems, intents, policies."""
    from . import analysis, insights
    start = now - timedelta(hours=24)
    events = _window_events(session, project.id, start, now)
    stats = insights.summary(events, start, now)
    signals = _signals(session, project.id, events)
    problems = {}
    for signal in signals:
        title = analysis.RULES[signal["kind"]]["title"]
        if signal["kind"] in ("tool_error", "tool_timeout", "policy_violation"):
            title += f' · {signal["tool_name"]}'
        problems.setdefault(title, set()).add(signal["conversation_id"])
    tools = insights.tool_stats(events, start, now)["tools"]
    findings = session.scalars(select(Classification).where(
        Classification.project_id == project.id, Classification.occurred_at >= start)).all()
    intents = Counter(r.label for r in findings if r.kind == "intent")
    policies = Counter(r.label for r in findings if r.kind == "policy")
    rate = f'{stats["success_rate"]}%' if stats["success_rate"] is not None else "n/a"
    lines = [f'{stats["total_conversations"]} conversations from {stats["active_users"]} users, '
             f'{stats["total_calls"]} operations, {rate} succeeded.']
    if problems:
        lines += ["", "Top problems:"] + [f"- {title}: {len(ids)} conversations" for title, ids in
                                          sorted(problems.items(), key=lambda item: -len(item[1]))[:5]]
    failing = [t for t in tools if t["errors"]]
    if failing:
        lines += ["", "Failing tools:"] + [f'- {t["name"]}: {t["errors"]} of {t["calls"]} calls failed' for t in failing[:5]]
    if intents:
        lines += ["", "Top intents:"] + [f"- {name}: {count}" for name, count in intents.most_common(5)]
    if policies:
        lines += ["", "Policy violations:"] + [f"- {name}: {count}" for name, count in policies.most_common(5)]
    if not events:
        lines = ["No conversations in the last 24 hours."]
    if dashboard_url:
        lines += ["", f"Open Tervik: {dashboard_url.rstrip('/')}/#overview"]
    return f"Daily summary for {project.name}", "\n".join(lines)


def intent_summary(session, project, now, dashboard_url=""):
    """New user needs that no configured intent covers. None when there are none."""
    rows = session.scalars(select(Classification).where(
        Classification.project_id == project.id, Classification.kind == "suggested",
        Classification.occurred_at >= now - timedelta(hours=24))).all()
    if not rows:
        return f"New intents for {project.name}", None
    counts = Counter(r.label for r in rows)
    reasons = {r.label: r.reason for r in rows if r.reason}
    lines = ["Users asked for things none of your intents cover:", ""]
    lines += [f"- {name} ({count} conversations)" + (f": {reasons[name]}" if name in reasons else "")
              for name, count in counts.most_common(10)]
    if dashboard_url:
        lines += ["", f"Review them: {dashboard_url.rstrip('/')}/#discovery"]
    return f"New intents for {project.name}", "\n".join(lines)


def process_deliveries(session, settings, limit=50):
    """Send due deliveries. Returns (sent, failed). Never raises."""
    now = utc_now()
    due = list(session.scalars(select(AlertDelivery).where(
        AlertDelivery.state.in_(("queued", "failed")),
        ((AlertDelivery.next_retry_at.is_(None)) | (AlertDelivery.next_retry_at <= now)))
        .order_by(AlertDelivery.created_at).limit(limit)))
    sent = failed = 0
    for delivery in due:
        if delivery.attempts >= MAX_DELIVERY_ATTEMPTS:
            delivery.state = "failed"
            delivery.error_code = delivery.error_code or "retry_exhausted"
            failed += 1
            continue
        rule = session.get(AlertRule, delivery.rule_id)
        target = None
        if rule is not None:
            for channel in rule_channels(rule):
                if channel["type"] == delivery.channel_type and hash_target(channel.get("target", "")) == delivery.target_hash:
                    target = channel.get("target")
                    break
        if not target:
            delivery.state = "failed"
            delivery.error_code = "channel_removed"
            failed += 1
            continue
        delivery.attempts += 1
        delivery.state = "sending"
        try:
            send(delivery.channel_type, target, delivery.title, delivery.body, settings)
            delivery.state = "sent"
            delivery.error_code = None
            delivery.sent_at = utc_now()
            sent += 1
        except ValueError as error:
            delivery.state = "failed"
            delivery.error_code = str(error)  # config errors do not retry blindly
            delivery.next_retry_at = None
            failed += 1
        except Exception as error:
            logger.warning("delivery attempt failed (%s)", type(error).__name__)
            if delivery.attempts >= MAX_DELIVERY_ATTEMPTS:
                delivery.state = "failed"
                delivery.error_code = "retry_exhausted"
                failed += 1
            else:
                delivery.state = "failed"
                delivery.error_code = "transient"
                delay = DELIVERY_BACKOFF[min(delivery.attempts - 1, len(DELIVERY_BACKOFF) - 1)]
                delivery.next_retry_at = utc_now() + timedelta(seconds=delay)
    session.flush()
    return sent, failed


def send(channel_type, target, title, body, settings=None):
    if channel_type == "slack":
        post_slack(target, title, body)
    elif channel_type == "webhook":
        post_webhook(target, title, body, settings)
    else:
        send_email(target, title, body, settings)


def slack_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def post_slack(url: str, title: str, body: str, timeout=10):
    """Slack incoming webhook with a bold title and the body as one section."""
    if not url.startswith("https://hooks.slack.com/"):
        raise ValueError("slack_not_configured")
    payload = json.dumps({"text": title, "blocks": [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{slack_escape(title)}*\n{slack_escape(body)}"[:2900]}}]}).encode()
    request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status >= 400:
                raise RuntimeError(f"http_{response.status}")
    except ValueError:
        raise
    except Exception as error:
        raise RuntimeError("slack_failed") from error


def post_webhook(url: str, title: str, body: str, settings=None, timeout=10):
    if not url.startswith(("http://", "https://")):
        raise ValueError("webhook_not_configured")
    payload = json.dumps({"text": f"{title}\n{body}"}).encode()
    request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status >= 400:
                raise RuntimeError(f"http_{response.status}")
    except ValueError:
        raise
    except Exception as error:
        raise RuntimeError("webhook_failed") from error


def send_email(to: str, title: str, body: str, settings=None):
    host = getattr(settings, "smtp_host", None)
    if not host or "@" not in to:
        raise ValueError("email_not_configured")
    message = EmailMessage()
    message["Subject"] = title
    message["From"] = getattr(settings, "smtp_from", "tervik@localhost")
    message["To"] = to
    message.set_content(body)
    try:
        with smtplib.SMTP(host, getattr(settings, "smtp_port", 25), timeout=10) as smtp:
            user = getattr(settings, "smtp_user", None)
            if user:
                smtp.login(user, getattr(settings, "smtp_password", ""))
            smtp.send_message(message)
    except Exception as error:
        raise RuntimeError("email_failed") from error
