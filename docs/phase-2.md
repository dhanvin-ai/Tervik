# Phase 2: accounts and durable ingestion

Implements section 5 of the saved roadmap. Phase 1 behavior is preserved:
legacy projects (`org_id` null) keep working through the existing routes,
and all 30 Phase 1 API tests pass unchanged.

## What was built

- Accounts: signup, login, logout, expiring hashed sessions (`POST /api/auth/*`,
  `GET /api/me`). Passwords are PBKDF2-hashed; session tokens are returned
  once and stored as SHA-256.
- Organizations and roles: owner/admin/member/viewer, member management with
  last-owner protection (`POST /api/orgs`, `/api/orgs/{id}/members`).
- Org projects and environments: projects owned by an org with a default
  environment (`POST /api/orgs/{id}/projects`).
- Credential lifecycle: ingest-only keys returned once, stored hashed with a
  display prefix, revocable, audited. Ingest keys cannot read customer data
  (401 on dashboard routes); revoked keys fail ingestion (401).
- Durable HTTP ingestion: `POST /v1/events` commits an outbox row per
  `(project_id, event_id)` before acknowledging. Workers materialize events,
  usage, and payload objects idempotently afterwards.
- OTLP ingestion: `POST /v1/otlp/traces` accepts OTLP TracesData JSON and
  normalizes spans to canonical events, preserving trace/span/parent ids so
  nested and out-of-order spans keep their relationships.
- Recovery and diagnostics: `GET /api/jobs` shows pending/processed/failed/
  dead/expired counts plus recent jobs without payload contents;
  `POST /api/jobs/{project}/{event}/replay` resets a job to pending.
  Bounded retries (5) with backoff, then dead-letter. ClickHouse mirror has
  its own retry budget (8) and never fails a committed SQL event.
- Capture and retention: per-project `capture_content`, `redact_keys`,
  `retention_days` (`PATCH /api/projects/{id}/capture`). Redaction runs
  before queue writes. `POST /api/projects/{id}/retention/run` deletes
  expired events, usage, jobs, and payload objects by source timestamp.
- Usage and audit: one usage row per logical event (retries charged once);
  audit records for signup, org/member, project, credential, capture,
  replay, and retention actions (`GET /api/orgs/{id}/audit`).
- Worker: `python workers/normalize.py [--once]` polls the outbox and
  retries mirrors. NATS (`NATS_URL`) is an optional wake-up transport; the
  database outbox is the durable core.

## Storage

PostgreSQL holds accounts, orgs, memberships, sessions, environments,
credentials, jobs, usage, audit, and payload objects. ClickHouse mirrors
ingested events. Large payloads (>= 8,000 chars) also land in
`payload_objects` locally; S3 (`S3_ENDPOINT`/`S3_BUCKET`) is documented for
later artifacts. Deploy SQL: `database/postgres/001_phase2.sql`.

## Completion gate

- Acknowledged events survive worker failure: covered by
  `test_ack_survives_worker_failure_and_retry_counts_once` (ack with the
  worker disabled, then process; nothing lost).
- Retries do not inflate counts: duplicate batches return
  `{accepted: 0, duplicates: N}`; events, usage, and mirror rows win once via
  unique `(project_id, event_id)` constraints.
- Cross-organization access fails: `test_cross_organization_access_fails`
  (unknown project ids return 404 across orgs; sessions cannot see legacy
  projects and vice versa).

## Screenshot mapping (Agnost parity targets)

The Agnost product screens map to later phases and are tracked here so
Phase 2 stays compatible: recurring-problem clusters (Phase 6), message
evidence views (Phase 3), message+trace source following (Phase 3/5),
approve-suggested-fix with replay (Phase 8/9), two-step skill install and
framework matrix (Phase 3/4). Phase 2 provides the durable, tenant-isolated
event foundation those screens read from.
