# Phase 9: suggested fixes and delivery

Implements section 12 of the saved roadmap up to repository delivery:
evidence-backed prompt suggestions with a guarded lifecycle, a versioned
prompt registry, and measured outcomes. Scoped repository integration
(exportable diffs) is provided; pushing into customer repositories stays
a customer-approved connector step.

## Lifecycle (all transitions guarded, all audited)

`proposed → investigating → candidate_ready → evaluating →
awaiting_approval → deployed → monitoring → resolved`, with `rolled_back`
from deployed/monitoring and `cancelled` from early states.

- Candidate readiness requires an exact diff; evaluation requires an
  attached run; approval requires a verifying run (verdict `improved` or
  `no_change`, zero regressions). Deploying, rolling back, or cancelling
  requires admin; intermediate steps require member.
- Deploying activates a new prompt-registry version and supersedes the
  prior active one. Rollback restores the predecessor and marks the
  deployed version rolled back. No deployment occurs before approval.

## Suggestions and measurement

- Suggestions are deterministic templates grounded in cited evidence
  (triggering event, proposed cause, explicit uncertainty, exact diff) —
  reviewable text, never silent automation.
- `GET /api/improvements/{id}/measurements` compares flagged rates
  before/after deployment; resolving records the measurements, and
  `insufficient_data` is reported instead of inventing an outcome.

## Gate

One issue completes propose → investigate → candidate → evaluate →
approve → deploy → monitor → resolve with verified delivery and recorded
measurements, plus a rollback that restores the prior prompt
(`test_phase9.py`). Repository investigation/patch-PR delivery is the
exported diff plus connector seam, tracked as the remaining Phase 9 item
alongside the skill-verification test deferred from Phase 3.
