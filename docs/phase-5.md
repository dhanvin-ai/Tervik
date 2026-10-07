# Phase 5: failure detection

Implements section 8 of the saved roadmap. Deterministic checks first;
model-based evaluation where context is required stays future work and is
marked as such below.

## Detectors (all evidenced, all versioned)

| Kind | Evidence | Severity |
|---|---|---|
| correction | explicit correction phrase in a user message | medium |
| frustration | explicit frustration language | high |
| repetition | same normalized request twice in a conversation | medium |
| tool_error | tool event with `status=error` | high |
| tool_timeout | error tool event with timeout text | high |
| unresolved | user explicitly states the issue persists | high |
| unsupported_claim | claimed action with no supporting successful tool call | high |
| rule_violation | customer behavior rule matched | rule severity |

Every signal carries supporting message/span ids, an explanation,
`detector_version` (`5.0.0`), a per-category `rule_version`, and review
status (via cluster resolve). Signals and clusters expose the versions in
the API and dashboard.

## Insufficient evidence

- Silence never proves abandonment: there is no abandonment detector.
- An unattributable claim abstains: when a claim has no trace linkage and
  the conversation has tool activity that cannot be tied to the turn, no
  finding is emitted.
- A `required_tool` rule with no assistant message in the conversation
  emits nothing.

## Behavior rules

Customer-owned, versioned definitions: `forbidden_phrase` (regex over
assistant messages) and `required_tool` (must succeed per conversation).
Managed in the dashboard failures page or via
`GET/POST /api/projects/{id}/rules` and `PATCH/DELETE /api/rules/{id}`
(admin role; audited). Invalid regexes are rejected at creation and
tolerated (no findings) at evaluation.

## Labeled evaluation

`tests/fixtures/detection-eval.json` holds 130+ labeled cases across all
eight categories plus abstention and healthy negatives.
`python3 scripts/evaluate_detection.py` (venv python) reports
precision/recall per category; `apps/api/tests/test_detection_eval.py`
enforces the gate: precision >= 0.90 and recall >= 0.70 per category.
Current result: 1.0 precision and recall in every category, 2 abstentions.
Expand the set by category with pilot data before releasing alerts; set
per-category release targets (90% precision for high-priority) against
that data.

## Not built (stays future work)

Model-based evaluation for context-dependent judgments, alert delivery
(Phase 7), and evaluation/replay runners (Phase 8). Evaluator content and
customer content remain separate; no detection component has deployment
authority.
