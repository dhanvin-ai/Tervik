"""Phase 5 detection evaluation: precision/recall per category on a labeled set.

Run: python3 scripts/evaluate_detection.py [--json]
Gate: precision >= 0.90 for every category, recall >= 0.70 for every
category. Abstentions (insufficient evidence) are reported, not penalized.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.analysis import RULES, analyze  # noqa: E402

CATEGORIES = ["correction", "frustration", "repetition", "tool_error", "tool_timeout",
              "unresolved", "unsupported_claim", "rule_violation"]
MIN_PRECISION = 0.90
MIN_RECALL = 0.70


def load_cases():
    with open(ROOT / "tests" / "fixtures" / "detection-eval.json") as handle:
        return json.load(handle)["cases"]


def make_event(raw, index, base):
    timestamp = base + timedelta(seconds=index)
    return SimpleNamespace(
        project_id="eval", id=raw.get("id", f"e-{index}"), conversation_id="conv-1",
        user_id="u-1", role=raw.get("role", "user"), content=raw.get("content", ""),
        timestamp=timestamp, trace_id=raw.get("trace_id"), span_id=raw.get("span_id"),
        parent_span_id=raw.get("parent_span_id"), name=raw.get("name"),
        status=raw.get("status", "success"), latency_ms=raw.get("latency_ms"),
        tokens=None, cost_usd=None, model=None, event_metadata={},
    )


def evaluate():
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    stats = {kind: {"tp": 0, "fp": 0, "fn": 0} for kind in CATEGORIES}
    abstentions, failures = 0, []
    for case in load_cases():
        events = [make_event(raw, index, base) for index, raw in enumerate(case["events"])]
        predicted = {s["kind"] for s in analyze(events, case.get("rules", []))}
        expected = set(case["expect"])
        if case.get("abstain"):
            abstentions += 1
        for kind in CATEGORIES:
            if kind in predicted and kind in expected:
                stats[kind]["tp"] += 1
            elif kind in predicted:
                stats[kind]["fp"] += 1
                failures.append((case["id"], f"false {kind}"))
            elif kind in expected:
                stats[kind]["fn"] += 1
                failures.append((case["id"], f"missed {kind}"))
    rows = {}
    for kind, counts in stats.items():
        tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        rows[kind] = {**counts, "precision": round(precision, 3), "recall": round(recall, 3),
                      "severity": RULES[kind]["severity"]}
    return rows, abstentions, failures


def main():
    rows, abstentions, failures = evaluate()
    if "--json" in sys.argv:
        print(json.dumps({"categories": rows, "abstentions": abstentions, "failures": failures}, indent=2))
        return 0 if not failures else 1
    print(f'{"category":<18}{"tp":>5}{"fp":>5}{"fn":>5}{"precision":>11}{"recall":>8}  severity')
    gate_ok = True
    for kind in CATEGORIES:
        row = rows[kind]
        ok = row["precision"] >= MIN_PRECISION and row["recall"] >= MIN_RECALL
        gate_ok = gate_ok and ok
        print(f'{kind:<18}{row["tp"]:>5}{row["fp"]:>5}{row["fn"]:>5}{row["precision"]:>11}{row["recall"]:>8}  {row["severity"]}{"" if ok else "  GATE FAIL"}')
    print(f"abstentions (insufficient evidence): {abstentions}")
    for case_id, problem in failures:
        print(f"  {case_id}: {problem}")
    print("GATE PASS" if gate_ok else "GATE FAIL")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
