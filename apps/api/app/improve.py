"""Phase 9 improvements: evidence-backed prompt suggestions with a guarded
delivery lifecycle.

No deployment occurs before approval, and rollback restores the prior
prompt version. Suggestions are deterministic templates grounded in the
cited evidence, not model output.
"""
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from .db import Event, Improvement, PromptVersion, utc, utc_now

IMPROVE_VERSION = "9.0.0"

TRANSITIONS = {
    "proposed": ("investigating", "cancelled"),
    "investigating": ("candidate_ready", "cancelled"),
    "candidate_ready": ("evaluating", "cancelled"),
    "evaluating": ("awaiting_approval",),
    "awaiting_approval": ("deployed",),
    "deployed": ("monitoring", "rolled_back"),
    "monitoring": ("resolved", "rolled_back"),
    "resolved": (),
    "rolled_back": (),
    "cancelled": (),
}

_TEMPLATES = {
    "unsupported_claim": {
        "title": "Require tool confirmation before reporting completion",
        "cause": "The assistant reported a completed action with no supporting successful tool call in the same turn.",
        "uncertainty": "Tool telemetry may be missing for this turn; confirm the tool truly did not run before changing instructions.",
        "lines": [
            "Always call {tool} for this request and quote its confirmed result.",
            "Never report the action as done from memory or assumption.",
        ],
    },
    "tool_error": {
        "title": "Add retry and fallback for failing tool",
        "cause": "The tool reported an explicit error and the agent had no recovery path.",
        "uncertainty": "The underlying service fault may be transient; verify against recent error rates.",
        "lines": [
            "When {tool} reports an error, retry once, then offer the user a manual alternative.",
            "Never present a failed tool result as a completed action.",
        ],
    },
    "tool_timeout": {
        "title": "Add deadline and fallback for slow tool",
        "cause": "The tool timed out and the agent left the user waiting without recourse.",
        "uncertainty": "Timeouts may come from load rather than logic; check latency trends first.",
        "lines": [
            "Give {tool} a bounded wait, then report progress and offer to continue in the background.",
            "Record timeouts explicitly instead of stalling the conversation.",
        ],
    },
    "correction": {
        "title": "Clarify the misunderstood requirement",
        "cause": "The user explicitly corrected the agent, so the original instruction was ambiguous.",
        "uncertainty": "One correction may be an outlier; check the cluster count before rewriting.",
        "lines": [
            "Restate the understood requirement and ask for confirmation when it is ambiguous.",
            "Prefer the user's most recent correction over earlier context.",
        ],
    },
    "frustration": {
        "title": "Recover explicitly when the user is frustrated",
        "cause": "Explicit frustration language followed an unhelpful turn.",
        "uncertainty": "Frustration may predate this conversation; confirm the trigger turn.",
        "lines": [
            "Acknowledge the obstacle directly, then try one concrete alternative.",
            "Do not repeat the same failed response twice in a row.",
        ],
    },
    "repetition": {
        "title": "Answer repeated requests with the earlier result",
        "cause": "The same normalized request appeared twice, so the first answer did not land.",
        "uncertainty": "Repetition can be intentional; confirm the earlier answer truly failed.",
        "lines": [
            "When a request repeats, reference the previous answer and ask what is still missing.",
            "Do not restart the full workflow without acknowledging the repeat.",
        ],
    },
    "unresolved": {
        "title": "Close the loop on unresolved requests",
        "cause": "The user explicitly stated the problem persists.",
        "uncertainty": "The remaining problem may differ from the original request.",
        "lines": [
            "Ask which part is still unresolved and confirm the fix before closing.",
            "Summarize what was tried so the user does not repeat themselves.",
        ],
    },
    "rule_violation": {
        "title": "Enforce the violated behavior rule",
        "cause": "A customer-defined behavior rule matched recorded telemetry.",
        "uncertainty": "The rule itself may need updating; review it alongside the evidence.",
        "lines": [
            "Restate the behavior rule as an explicit step in the agent instructions.",
            "Check compliance with the rule before composing the final response.",
        ],
    },
}


def suggest(kind, tool=None, evidence_text=""):
    """Build an evidence-backed suggestion draft. Deterministic, no model."""
    template = _TEMPLATES.get(kind, _TEMPLATES["correction"])
    name = tool or "the relevant tool"
    lines = [line.format(tool=name) for line in template["lines"]]
    path = "prompts/support-agent.md"
    diff = f"*** path: {path}\n" + "".join(f"+ {line}\n" for line in lines)
    evidence = f"Cited evidence: {evidence_text[:200]}" if evidence_text else "Cited evidence: cluster review"
    return {
        "title": template["title"],
        "cause": f"{template['cause']} {evidence}",
        "uncertainty": template["uncertainty"],
        "prompt_path": path,
        "prompt_content": "\n".join(lines),
        "candidate_diff": diff,
    }


def public_improvement(imp):
    return {"id": imp.id, "project_id": imp.project_id, "title": imp.title,
            "signal_kind": imp.signal_kind, "evidence": imp.evidence or [],
            "cause": imp.cause, "uncertainty": imp.uncertainty,
            "candidate_diff": imp.candidate_diff, "state": imp.state,
            "eval_run_id": imp.eval_run_id, "approved_by": imp.approved_by,
            "deployed_at": imp.deployed_at.isoformat().replace("+00:00", "Z") if imp.deployed_at else None,
            "measurements": imp.measurements or {},
            "created_at": imp.created_at.isoformat().replace("+00:00", "Z")}


def check_transition(imp, to_state, session=None):
    """Validate a lifecycle move. Returns (ok, reason)."""
    allowed = TRANSITIONS.get(imp.state, ())
    if to_state not in allowed:
        return False, f"cannot move from {imp.state} to {to_state}"
    if to_state == "candidate_ready" and not (imp.candidate_diff or "").strip():
        return False, "candidate needs an exact diff first"
    if to_state == "evaluating" and not imp.eval_run_id:
        return False, "attach an evaluation run first"
    if to_state == "awaiting_approval" and imp.eval_run_id and session is not None:
        from .db import EvalRun
        run = session.get(EvalRun, imp.eval_run_id)
        results = (run.results or {}) if run else {}
        if results.get("regressed"):
            return False, "evaluation shows regressions"
        if results.get("verdict") not in ("improved", "no_change"):
            return False, "evaluation did not verify the candidate"
    return True, ""


def activate_prompt(session, project_id, path, content, improvement_id, account_id):
    """Activate a new prompt version; supersede the prior active one."""
    current = session.scalars(select(PromptVersion).where(
        PromptVersion.project_id == project_id, PromptVersion.path == path)).all()
    version = max([p.version for p in current] + [0]) + 1
    for previous in current:
        if previous.status == "active":
            previous.status = "superseded"
    record = PromptVersion(id=str(uuid4()), project_id=project_id, path=path,
                           content=content, version=version, status="active",
                           improvement_id=improvement_id, created_by=account_id)
    session.add(record)
    session.flush()
    return record


def rollback_prompt(session, project_id, path):
    """Restore the most recent non-rolled-back predecessor as active."""
    versions = sorted(session.scalars(select(PromptVersion).where(
        PromptVersion.project_id == project_id, PromptVersion.path == path)).all(),
        key=lambda p: p.version, reverse=True)
    current = next((p for p in versions if p.status == "active"), None)
    if current is not None:
        current.status = "rolled_back"
    predecessor = next((p for p in versions
                        if p.status in ("superseded", "draft") and p != current), None)
    if predecessor is None:
        return None
    predecessor.status = "active"
    return predecessor


def measure_outcome(session, project_id, signal_kind, deployed_at, window_days=7):
    """Before/after flagged-conversation rates around deployment."""
    from . import analysis
    if deployed_at is None:
        return {"status": "not_deployed"}
    deployed_at = utc(deployed_at)
    events = list(session.scalars(select(Event).where(Event.project_id == project_id)))
    before_start = deployed_at - timedelta(days=window_days)
    before = [e for e in events if before_start <= utc(e.timestamp) < deployed_at]
    after = [e for e in events if deployed_at <= utc(e.timestamp) <= utc_now()]
    if not before or not after:
        return {"status": "insufficient_data", "before_n": len(before), "after_n": len(after)}
    from collections import defaultdict
    def rate(messages):
        by_conv = defaultdict(list)
        for event in messages:
            by_conv[event.conversation_id].append(event)
        flagged = sum(1 for ms in by_conv.values()
                      if any(s["kind"] == signal_kind for s in analysis.analyze(ms)))
        return 100.0 * flagged / len(by_conv), len(by_conv)
    before_rate, before_n = rate(before)
    after_rate, after_n = rate(after)
    return {"status": "measured", "signal_kind": signal_kind,
            "before_rate": round(before_rate, 2), "after_rate": round(after_rate, 2),
            "before_n": len(before), "after_n": len(after),
            "improvement_pct": round(100.0 * (before_rate - after_rate) / before_rate, 1)
            if before_rate else 0.0,
            "conversations_before": before_n, "conversations_after": after_n}


def parse_prompt_block(candidate_diff):
    """Split the stored diff into (path, added_lines)."""
    path, added = "prompts/support-agent.md", []
    for line in (candidate_diff or "").splitlines():
        if line.startswith("*** path:"):
            path = line.split("*** path:", 1)[1].strip() or path
        elif line.startswith("+ "):
            added.append(line[2:])
    return path, added
