# Phase 7: alerts and paid beta

Implements section 10 of the saved roadmap up to the pilot gate. Paid-beta
scope (skill, Python/TS support, conversations, traces, intents,
violations, clusters, alerts, administration) is served by this build.

## Alerts

- Rule kinds: `threshold` (flagged conversations in a lookback window),
  `trend` (change vs the prior equal window), `summary` (daily digest).
  Each rule has lookback windows, minimum sample sizes, cooldowns, and
  channel lists. `GET/POST /api/projects/{id}/alerts`,
  `PATCH/DELETE /api/alerts/{id}`.
- A qualifying finding sends once: dedup keys per rule + window bucket,
  cooldown enforcement, and atomic duplicate rejection.
- Deliveries: Slack-compatible webhooks and SMTP email with bounded
  retries (8, backoff to ~4 days) and safe error codes. Failed deliveries
  stay visible with their error and replay safely
  (`POST /api/deliveries/{id}/replay`). Channel secrets live on the rule
  and are never returned; deliveries store only a target hash.
- Resolution tracking: rules flip `firing → ok` with `resolved_at` when
  the condition clears and minimum samples are met.
- Worker: `python workers/alert.py [--once]` evaluates enabled rules and
  sends due deliveries; killing it loses nothing (evaluation only queues).

## Commercial and lifecycle

- Usage metering and plan enforcement: per-organization monthly event
  limits (default beta 100k), `GET /api/orgs/{id}/billing`, over-quota
  ingestion returns 429. A payment provider plugs into the plan seam;
  no charges exist in this build.
- Retention (per-project days + runner), export
  (`GET /api/projects/{id}/export`, capped, audited), and full project
  deletion (`DELETE /api/projects/{id}`, audited).
- Operations: `GET /api/ops/summary` reports queue backlog, oldest
  pending age, 24h delivery success rate, analysis coverage, and usage —
  scoped to the caller's organizations.
- Backup: `python3 scripts/backup_check.py` snapshots SQLite and verifies
  row counts; PostgreSQL deploys use pg_dump/pg_restore with per-table
  count comparison.

## Gate status

Code-complete except the human part: three pilot teams independently
installing, investigating, and receiving alerts (`docs/onboarding.md` is
the runbook; per-team exit criteria are setup rate, one finding, one
alert). Record results here before calling Phase 7 done.
