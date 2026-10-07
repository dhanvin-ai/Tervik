# Tervik operational runbooks

## Symptoms and first checks

`GET /api/ops/summary` is the source of truth: queue backlog and oldest
pending age, 24h delivery success rate, analysis coverage, and usage.

| Symptom | Check | Action |
|---|---|---|
| Dashboard shows no new conversations | ops backlog growing; oldest pending age rising | Start `python workers/normalize.py`; jobs are durable and will drain |
| Alerts not arriving | deliveries_24h success rate; delivery error codes | `config_missing`/`channel_removed`: fix the rule channel; `transient`: worker retries; replay manually via `POST /api/deliveries/{id}/replay` |
| Spike in flagged conversations | Failure clusters evidence; detection eval | Investigate evidence before changing the agent; add a behavior rule for repeats |
| Ingest 429s | Org billing usage vs limit | Raise the plan limit or reduce capture; retries never double-charge |

## Key rotation

Ingest credentials are hashed and shown once. To rotate: create the new
credential (`POST /api/projects/{id}/credentials`), deploy it to server
secrets, verify traffic on the setup page, then revoke the old one
(`POST /api/credentials/{id}/revoke`). Revocation takes effect
immediately; audit records both actions. Sessions revoke on logout;
compromised sessions are revoked server-side by logging out.

## Restore from backup

SQLite: `python3 scripts/backup_check.py --database ./.data/tervik.db`
verifies a restored copy by row counts. PostgreSQL: `pg_dump` on schedule;
restore to a staging database and compare per-table counts before
promoting. ClickHouse mirrors rebuild from SQL projections by replaying
ingestion jobs; payload objects follow retention deadlines.

## Upgrades

Check `GET /api/compat` for the minimum supported client versions before
upgrading the API. Clients send `X-Tervik-Client`; versions older than the
floor keep working on the stable events-v2 contract but should upgrade.
Database changes are additive (`database/postgres/001_phase2.sql`);
`python3 scripts/migrate.py --check` verifies all tables exist.
