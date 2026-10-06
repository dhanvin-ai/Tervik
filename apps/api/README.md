# Tervik API

From `apps/api`:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Default durable storage is `sqlite:///./.data/tervik.db`, relative to the launch directory. `DATABASE_URL=postgresql+psycopg://...` selects PostgreSQL. Schema creation is automatic for this foundation; versioned database migrations are still pending.

`TERVIK_ADMIN_TOKEN` guards every `/api/*` route except `/api/health`. Project ingest keys are required for `/v1/events` and cannot authorize dashboard routes. Local mode without the admin token should bind localhost. Project keys are stored retrievably in SQL for the integration setup endpoint; production key management and user/workspace authentication are pending. `TERVIK_CORS_ORIGINS` is a comma-separated allowlist, defaulting to localhost and 127.0.0.1 on port 5173.

`POST /api/demo/seed` creates **Sample workspace**, with all events marked `metadata.sample=true`. Repeating it preserves the same project/events. `TERVIK_DEMO_ENABLED=false` disables seeding. Demo seeding defaults to disabled when an admin token is configured. No sample data is inserted automatically by the API.

The request limit is 4 MiB (`TERVIK_MAX_BODY_BYTES`); validated batches contain 1–100 events. Unknown fields (including supplied `project_id`) are rejected. Timestamps require a timezone, are normalized to UTC, and cannot be over five minutes into the future. SQL primary keys deduplicate `(project_id, event_id)` in a transaction, including concurrent requests. Duplicate IDs keep the first stored payload. Customer conversation IDs are mapped into stable, globally unique dashboard IDs per project.

Analysis is explicitly `rule_based`: correction phrases, frustration phrases, repeated normalized requests of at least eight characters, and explicit tool error statuses. It does not infer abandonment, churn, or semantic topic clusters. Clusters group signals by kind, and tool errors additionally by tool name. Counts use distinct affected conversations; failure rate means conversations with at least one heuristic signal. Anonymous users do not inflate affected-user counts. Missing latency/cost values are not estimated; average latency uses supplied event latencies. Resolution changes only review status, retaining evidence and failure counts.

Ranges are rolling 24-hour, 7-day, or 30-day UTC windows, including their boundaries and excluding future events. Daily trend buckets cover every UTC calendar date intersecting the window (so a 7-day rolling window can touch eight dates). Conversation lists/counts reflect events inside the window; conversation detail contains all recorded events. A conversation spanning multiple days may appear once on each applicable daily trend bucket. Cluster trend compares affected conversations with the immediately preceding equal-length window. A positive count with no prior count is represented as +100%, a display convention rather than a mathematically defined growth rate.

Optional ClickHouse event mirror: install `.[clickhouse]`, then set `CLICKHOUSE_URL=http://localhost:8123`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`, and `CLICKHOUSE_DATABASE` (default `tervik`). Background tasks create `{database}.events` and copy newly accepted SQL events. Dashboard reads remain SQL-backed. Mirroring is **best effort**: errors preserve ingestion success and log a non-sensitive warning, with no durable retry/outbox or historical backfill. Each batch opens its own client. Distributed workers, analytics at scale, migrations, retention/redaction, alerts, OAuth, and production SaaS authentication are pending.
