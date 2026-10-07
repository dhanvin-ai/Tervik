"""Phase 7 alerts: threshold/trend evaluation, summaries, deliveries.

Rules fire at most once per cooldown window per rule (dedup key), failed
deliveries retry with bounded backoff, and resolution is tracked when the
condition clears. Channel secrets live on the rule and are never returned
by the API or stored on deliveries (only a hash).
"""
import hashlib
import json
import logging
import smtplib
import urllib.request
from datetime import timedelta
from email.message import EmailMessage
from uuid import uuid4

from sqlalchemy import func, select

from .db import (AlertDelivery, AlertRule, Event, utc, utc_now)

logger = logging.getLogger(__name__)

MAX_DELIVERY_ATTEMPTS = 8
DELIVERY_BACKOFF = [60, 300, 1800, 7200, 21600, 86400, 172800, 345600]


def hash_target(target: str) -> str:
    return hashlib.sha256(target.encode()).hexdigest()[:16]


def rule_channels(rule) -> list:
    channels = rule.channels or []
    return [c for c in channels if isinstance(c, dict) and c.get("type") in ("webhook", "email")]


def public_rule(rule):
    return {"id": rule.id, "project_id": rule.project_id, "name": rule.name,
            "kind": rule.kind, "signal_kind": rule.signal_kind,
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


def _flagged_counts(session, project_id, kind, start, end):
    from . import analysis
    events = list(session.scalars(select(Event).where(
        Event.project_id == project_id).order_by(Event.timestamp, Event.id)))
    in_window = [e for e in events if start <= utc(e.timestamp) <= end]
    if kind:
        signals = [s for s in analysis.analyze(in_window) if s["kind"] == kind]
    else:
        signals = analysis.analyze(in_window)
    flagged = {s["conversation_id"] for s in signals}
    total = {e.conversation_id for e in in_window}
    return len(flagged), len(total)


def evaluate_rule(session, rule, now=None):
    """Check one rule. Returns (fired, detail). Creates queued deliveries."""
    now = now or utc_now()
    window = timedelta(hours=rule.window_hours or 24)
    if rule.kind == "summary":
        bucket = now.strftime("%Y-%m-%d")
        return _fire(session, rule, bucket, "Daily summary", "See the dashboard for details.", now)
    current, total = _flagged_counts(session, rule.project_id, rule.signal_kind,
                                     now - window, now)
    if total < (rule.min_samples or 0):
        _resolve(session, rule, now)
        return False, {"reason": "below_min_samples", "flagged": current, "total": total}
    if rule.kind == "threshold":
        if current < rule.threshold:
            _resolve(session, rule, now)
            return False, {"flagged": current, "total": total}
        detail = {"flagged": current, "total": total, "threshold": rule.threshold}
    elif rule.kind == "trend":
        prior, prior_total = _flagged_counts(session, rule.project_id, rule.signal_kind,
                                             now - 2 * window, now - window)
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
    title = f'{rule.name}: {current} flagged conversations'
    body = json.dumps(detail)
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


def build_summary(session, project_id, project_name) -> tuple[str, str]:
    from . import analysis
    now = utc_now()
    events = list(session.scalars(select(Event).where(Event.project_id == project_id)))
    recent = [e for e in events if utc(e.timestamp) >= now - timedelta(hours=24)]
    signals = analysis.analyze(recent)
    kinds = {}
    for signal in signals:
        kinds[signal["kind"]] = kinds.get(signal["kind"], 0) + 1
    lines = [f"{kind}: {count}" for kind, count in sorted(kinds.items())]
    body = (f"{project_name}: {len({e.conversation_id for e in recent})} conversations, "
            f"{len(recent)} messages in 24h. " + ("Signals: " + ", ".join(lines) if lines else "No signals."))
    return f"Daily summary for {project_name}", body


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
            if delivery.channel_type == "webhook":
                post_webhook(target, delivery.title, delivery.body, settings)
            else:
                send_email(target, delivery.title, delivery.body, settings)
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
