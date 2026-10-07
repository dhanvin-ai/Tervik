"""Phase 6 gate: discovery grouping quality on the tiered fixture."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from evaluate_discovery import (MIN_PRECISION, MIN_REPEATED_RECALL,  # noqa: E402
                                evaluate)


def test_discovery_quality_gate():
    result = evaluate()
    assert result["precision"] >= MIN_PRECISION, result
    assert result["repeated_recall"] >= MIN_REPEATED_RECALL, result
