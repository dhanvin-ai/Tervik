"""Phase 5 gate: detection precision/recall on the labeled dataset."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from evaluate_detection import CATEGORIES, MIN_PRECISION, MIN_RECALL, evaluate  # noqa: E402


def test_detection_precision_recall_gate():
    rows, abstentions, failures = evaluate()
    assert abstentions >= 2, "expected insufficient-evidence abstentions in the dataset"
    for kind in CATEGORIES:
        row = rows[kind]
        assert row["precision"] >= MIN_PRECISION, (kind, row, failures)
        assert row["recall"] >= MIN_RECALL, (kind, row, failures)
