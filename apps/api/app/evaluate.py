"""Phase 8 evaluation runner: recorded-tool replay, no live systems.

A case pins the conversation input, the recorded tool responses, and the
expectations. An agent descriptor pins the code path under test (tool plan
+ response template + version). The runner replays recorded outputs,
rebuilds the transcript, and scores outcomes, rule compliance, latency,
and cost. Unrecorded tools fail closed (sandbox isolation). Repeats are
aggregated to show stability; deterministic descriptors reproduce exactly.
"""
import re
import time
from types import SimpleNamespace
from uuid import uuid4

RUNNER_VERSION = "8.0.0"


def _event(project_id, conversation_id, role, content, **fields):
    return SimpleNamespace(
        project_id=project_id, id=fields.get("id", str(uuid4())), conversation_id=conversation_id,
        user_id="eval-user", role=role, content=content,
        timestamp=fields.pop("timestamp", None), trace_id=fields.get("trace_id"),
        span_id=fields.get("span_id"), parent_span_id=fields.get("parent_span_id"),
        name=fields.get("name"), status=fields.get("status", "success"),
        latency_ms=fields.get("latency_ms"), tokens=None, cost_usd=fields.get("cost_usd"),
        model=fields.get("model"), event_metadata=fields.get("metadata", {}),
    )


def run_case(project_id, case, agent):
    """Replay one case for one agent descriptor. Returns a result dict."""
    from datetime import datetime, timedelta, timezone
    from . import analysis
    now = datetime.now(timezone.utc)
    conversation_id = f"eval-{case['id']}"
    trace_id = f"eval-trace-{case['id']}"
    clock = [now]

    def tick():
        clock[0] = clock[0] + timedelta(milliseconds=1)
        return clock[0]

    def make(role, content, name=None, status="success", index=0, **extra):
        return _event(project_id, conversation_id, role, content,
                      **{"id": f"eval-{case['id']}-{index}", "timestamp": tick(),
                         "trace_id": trace_id, "name": name, "status": status, **extra})
    recorded = {t["name"]: t.get("recorded_output", "") for t in case.get("tools", [])}
    events = [make("user", case["input"], index=0)]
    called, missing, skipped = [], [], []
    plan = agent.get("tools_plan", []) or []
    for position, step in enumerate(plan):
        name = step.get("name", "")
        if name in recorded:
            called.append(name)
            events.append(_event(
                project_id, conversation_id, "tool", str(recorded[name]),
                **{"id": f"eval-{case['id']}-tool-{position}", "timestamp": tick(),
                   "trace_id": trace_id, "span_id": f"eval-{case['id']}-span-{position}",
                   "name": name, "status": "success",
                   "metadata": {"input": step.get("args", {}), "output": recorded[name]}}))
        else:
            (skipped if step.get("optional") else missing).append(name)
    template = agent.get("response_template", "{input}")
    try:
        response = template.format(input=case["input"],
                                   tools=", ".join(f"{n}={recorded[n]}" for n in called))
    except (KeyError, IndexError, ValueError):
        response = template
    events.append(_event(project_id, conversation_id, "assistant", response,
                         **{"id": f"eval-{case['id']}-assistant", "timestamp": tick(),
                            "trace_id": trace_id, "span_id": f"eval-{case['id']}-turn",
                            "name": "eval.turn", "status": "success" if not missing else "success",
                            "model": agent.get("model"), "latency_ms": agent.get("latency_ms"),
                            "cost_usd": agent.get("cost_usd"),
                            "metadata": {"input": case["input"], "output": response}}))
    started = time.perf_counter()
    signals = analysis.analyze(events)
    elapsed_ms = (time.perf_counter() - started) * 1000
    expected = {k: v for k, v in (case.get("expected", {}) or {}).items() if v is not None}
    checks = {}
    if "response_contains" in expected:
        checks["response_contains"] = str(expected["response_contains"]) in response
    if "response_regex" in expected:
        checks["response_regex"] = bool(re.search(expected["response_regex"], response, re.I))
    if "tools_called" in expected:
        checks["tools_called"] = all(t in called for t in expected["tools_called"])
    if expected.get("no_violations"):
        banned = set(expected["no_violations"])
        checks["no_violations"] = not any(s["kind"] in banned for s in signals)
    checks["no_missing_tools"] = not missing
    passed = all(checks.values()) if checks else True
    return {
        "case_id": case["id"], "passed": passed, "checks": checks,
        "called_tools": called, "missing_tools": missing, "skipped_tools": skipped,
        "response": response[:500],
        "violations": [{"kind": s["kind"], "reason": s["reason"]} for s in signals],
        "latency_ms": round(elapsed_ms, 3),
        "cost_usd": agent.get("cost_usd", 0),
        "runner_version": RUNNER_VERSION,
    }


def run_dataset(project_id, cases, baseline, candidate, repeats=1):
    """Compare candidate vs baseline over repeats. Pure + reproducible."""
    repeats = max(1, min(int(repeats or 1), 5))
    case_results, stable = [], True
    first_seen = {}
    for _ in range(repeats):
        for case in cases:
            base = run_case(project_id, case, baseline)
            cand = run_case(project_id, case, candidate)
            key = (case["id"],)
            signature = (base["passed"], cand["passed"], base["response"], cand["response"])
            if key in first_seen and first_seen[key] != signature:
                stable = False
            first_seen[key] = signature
            case_results.append({"case_id": case["id"], "baseline": base, "candidate": cand})
    seen, deduped = set(), []
    for row in case_results:
        if row["case_id"] not in seen:
            seen.add(row["case_id"])
            deduped.append(row)
    fixed = [r["case_id"] for r in deduped if r["candidate"]["passed"] and not r["baseline"]["passed"]]
    regressed = [r["case_id"] for r in deduped if not r["candidate"]["passed"] and r["baseline"]["passed"]]
    base_pass = sum(1 for r in deduped if r["baseline"]["passed"])
    cand_pass = sum(1 for r in deduped if r["candidate"]["passed"])
    base_violations = sum(len(r["baseline"]["violations"]) for r in deduped)
    cand_violations = sum(len(r["candidate"]["violations"]) for r in deduped)
    return {
        "cases": len(deduped), "repeats": repeats, "reproducible": stable,
        "baseline_pass": base_pass, "candidate_pass": cand_pass,
        "fixed": fixed, "regressed": regressed,
        "baseline_violations": base_violations, "candidate_violations": cand_violations,
        "verdict": ("improved" if fixed and not regressed else
                    "regressed" if regressed else
                    "no_change" if cand_pass == base_pass else "mixed"),
        "details": deduped,
        "runner_version": RUNNER_VERSION,
    }
