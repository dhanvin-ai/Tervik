"""Phase 6 discovery evaluation: pairwise grouping quality, tiered.

Tiers (see tests/fixtures/clustering-eval.json):
- repeated: near-verbatim recurring phrasings, the production shape for
  recurring problems. Gate: precision >= 0.85, recall >= 0.70 on pairs
  where both sides are repeated-tier.
- paraphrase: uniquely-worded same-topic texts. Needs semantic (model)
  embeddings; reported, not gated. Tracks the embedding-adapter gap.

Run: apps/api/.venv/bin/python scripts/evaluate_discovery.py
"""
import json
import sys
import warnings
from itertools import combinations
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.clustering import discover  # noqa: E402

MIN_PRECISION = 0.85
MIN_REPEATED_RECALL = 0.70


def load_units():
    with open(ROOT / "tests" / "fixtures" / "clustering-eval.json") as handle:
        groups = json.load(handle)["groups"]
    units = []
    for group in groups:
        for counter, text in enumerate(group.get("repeated", [])):
            units.append({"id": f"{group['name']}-r{counter}", "truth": group["name"],
                          "tier": "repeated", "text": text})
        for counter, text in enumerate(group.get("paraphrase", [])):
            tier = "singleton" if group["name"] == "unrelated" else "paraphrase"
            truth = f"unrelated-{counter}" if group["name"] == "unrelated" else group["name"]
            units.append({"id": f"{group['name']}-p{counter}", "truth": truth,
                          "tier": tier, "text": text})
    return units


def evaluate():
    units = load_units()
    by_id = {u["id"]: u for u in units}
    predicted = {}
    for group in discover([{"id": u["id"], "text": u["text"]} for u in units]):
        for member in group["member_ids"]:
            predicted[member] = group["key"]
    tp = fp = fn = 0
    rep_tp = rep_fn = 0
    mistakes = []
    for first, second in combinations([u["id"] for u in units], 2):
        a, b = by_id[first], by_id[second]
        same_truth = a["truth"] == b["truth"]
        same_predicted = first in predicted and predicted.get(first) == predicted.get(second)
        repeated_pair = a["tier"] == "repeated" and b["tier"] == "repeated"
        if same_truth and same_predicted:
            tp += 1
        elif not same_truth and same_predicted:
            fp += 1
            mistakes.append(f"merged {first} + {second}")
        elif same_truth and not same_predicted:
            fn += 1
        if same_truth and repeated_pair and same_predicted:
            rep_tp += 1
        elif same_truth and repeated_pair:
            rep_fn += 1
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    rep_total = rep_tp + rep_fn
    rep_recall = rep_tp / rep_total if rep_total else 1.0
    return {"precision": round(precision, 3), "recall": round(recall, 3),
            "repeated_recall": round(rep_recall, 3),
            "tp": tp, "fp": fp, "fn": fn, "repeated_pairs": rep_total,
            "clustered": len(predicted), "total": len(units),
            "mistakes": mistakes[:20]}


def main():
    result = evaluate()
    print(json.dumps(result, indent=2))
    ok = (result["precision"] >= MIN_PRECISION
          and result["repeated_recall"] >= MIN_REPEATED_RECALL)
    print("GATE PASS" if ok else "GATE FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
