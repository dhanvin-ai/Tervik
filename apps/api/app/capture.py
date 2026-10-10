"""Phase 2 capture settings, redaction, and retention helpers.

Redaction runs before durable queue writes so sensitive content never
reaches a sink. Retention uses source timestamps.
"""
import re
from datetime import timedelta

SECRET_PATTERNS = [
    re.compile(r"sk-(?:live|test)-[A-Za-z0-9_-]{8,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"xox[bap]- [A-Za-z0-9-]+".replace(" ", "")),
    re.compile(r"ghp_[A-Za-z0-9]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/=]{10,}"),
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?([^'\"\s,}]{6,})['\"]?"),
]

REDACTED = "[redacted]"

DEFAULT_SETTINGS = {
    "capture_content": True,
    "redact_keys": [],
    "retention_days": 90,
    # Accept the project ID as a public, write-only ingestion identifier.
    "public_ingest": True,
}


def project_settings(project) -> dict:
    merged = dict(DEFAULT_SETTINGS)
    merged.update(getattr(project, "settings", None) or {})
    return merged


def redact_text(text: str, extra_keys: list[str] | None = None) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    for key in extra_keys or []:
        if key:
            redacted = redacted.replace(key, REDACTED)
    return redacted


def redact_value(value, extra_keys: list[str] | None = None):
    if isinstance(value, str):
        return redact_text(value, extra_keys)
    if isinstance(value, dict):
        return {key: redact_value(item, extra_keys) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item, extra_keys) for item in value]
    return value


def apply_capture(content: str, metadata: dict, settings: dict) -> tuple[str, dict]:
    """Apply capture policy. Returns (content, metadata) safe to persist."""
    extra = list(settings.get("redact_keys") or [])
    metadata = redact_value(metadata, extra)
    if not settings.get("capture_content", True):
        return "", metadata
    return redact_text(content, extra), metadata


def retention_cutoff(retention_days: int, now):
    return now - timedelta(days=retention_days)
