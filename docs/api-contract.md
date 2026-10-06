# Tervik foundation API contract

This contract is shared by the dashboard, ingestion service, SDK, and downloadable skill. The foundation runs locally; dashboard endpoints are development-only unless an administrator token is configured. Ingest always requires a per-project key. JSON field names use snake_case. All times are ISO 8601 UTC; rates/shares use percentages from 0 to 100. All list endpoints return arrays unless noted otherwise.

## Dashboard

- `GET /api/health` → `{status, storage, analysis_mode}`.
- `GET /api/projects` → `Project[]` (never include secret keys).
- `POST /api/projects` body `{name}` → `Project` plus newly created `api_key`.
- `GET /api/projects/{id}/key` → `{api_key}` for local/admin integration setup.
- `GET /api/overview?project_id=...&range=7d` → `{project, metrics, trend, top_clusters, recent_conversations, analysis_mode}`. Range is `24h`, `7d`, or `30d`.
- `GET /api/clusters?project_id=...&range=7d&search=...&status=open` → `Cluster[]`. Status/search optional.
- `GET /api/clusters/{id}?range=7d` → `Cluster` plus `{conversations, evidence}`. Range filters evidence and counts.
- `PATCH /api/clusters/{id}` body `{status: "open"|"resolved"}` → updated `Cluster`.
- `GET /api/conversations?project_id=...&range=7d&search=...&flagged=true` → `ConversationSummary[]`. Search/flagged optional.
- `GET /api/conversations/{id}` → `ConversationSummary` plus `{messages: Event[], signals: Signal[], spans: Span[]}`.
- `POST /api/demo/seed` → `{seeded, project_id}`. Idempotent sample workspace, explicitly demo data.

Dashboard authorization: optional `Authorization: Bearer <TERVIK_ADMIN_TOKEN>`. Without this setting, local developer mode is enabled; bind localhost by default. Keys are visible only through the setup endpoint, not list responses. Ingestion keys must not authorize administrator routes.

### Shapes

`Project`: `{id, name, slug, created_at, is_demo}`.

`metrics`: `{conversations, messages, failure_rate, affected_users, avg_latency_ms, cost_usd}`.

`trend`: `[{date, conversations, failures}]`.

`Cluster`: `{id, project_id, title, description, severity, kind, status, count, affected_users, share, trend, created_at, last_seen, suggested_fix}`. Severity is `critical|high|medium|low`. Kind is `correction|frustration|repetition|tool_error|abandonment`. Trend is a signed percentage.

`ConversationSummary`: `{id, project_id, user_id, started_at, last_at, message_count, latency_ms, status, tags, preview, model, cost_usd}`. Status is `healthy|flagged`; tags are strings.

`Signal`: `{id, event_id, conversation_id, kind, reason, severity}`.

`evidence`: `[{event_id, conversation_id, content, reason}]`.

`Span`: `{id, parent_id, name, kind, status, duration_ms, input, output}`. Nullable parent. Input/output may be strings or JSON values.

## Ingestion

`POST /v1/events` with `Authorization: Bearer <project_key>` and body `{events: Event[]}` → `{accepted, duplicates}`. Batch limit 100; event ids deduplicate within project. The key determines project; supplied project ids must never override it. Reject malformed batches atomically.

`Event`: `{id?, conversation_id, user_id?, role, content, timestamp?, trace_id?, span_id?, parent_span_id?, name?, status?, latency_ms?, tokens?, cost_usd?, model?, metadata?}`. Role is `user|assistant|tool|system`. Status is `success|error`; default success. Content is a string. Timestamp defaults to server time; event id defaults to UUID. Latency/cost/tokens are nonnegative. Metadata defaults to `{}` and may contain span input/output. Maximum content length 32,000 characters; batch body limited by API.

Analysis in this milestone is deterministic, rule-based triage, explicitly labeled in the UI. It detects evidenced user corrections/frustration, repeated user requests, and tool errors. Abandonment requires an elapsed-time criterion and must not be inferred merely because a conversation currently ends with a user message. Suggestions are reviewable text; resolving a cluster never changes a customer's agent.

## Storage scope

SQLite is the zero-configuration local development adapter. PostgreSQL is the deployable metadata adapter. Optional ClickHouse mirrors ingested events for analytical storage; this milestone does not claim a finished distributed worker or production SaaS authentication. Document what is implemented, configured, and still pending separately.
