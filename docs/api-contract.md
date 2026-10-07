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

`Signal`: `{id, event_id, conversation_id, kind, reason, severity, detector_version, rule_version}`.

`Cluster` gains `{detector_version, rule_version}`.

`BehaviorRule`: `{id, project_id, name, kind, pattern, tool, severity, enabled, version, created_at}`. Kind is `forbidden_phrase|required_tool`.

- `GET /api/projects/{id}/rules` → `BehaviorRule[]`.
- `POST /api/projects/{id}/rules` body `{name, kind, pattern?, tool?, severity?}` → `BehaviorRule` (admin+).
- `PATCH /api/rules/{id}` body `{enabled?, severity?}` → `BehaviorRule` (admin+).
- `DELETE /api/rules/{id}` → `{ok}` (admin+).

## Phase 6: intents and discovery

`Intent`: `{id, project_id, name, description, examples, enabled, version, created_at}`.

- `GET /api/projects/{id}/intents` → `Intent[]`.
- `POST /api/projects/{id}/intents` body `{name, description?, examples[]}` → `Intent` (admin+).
- `PATCH /api/intents/{id}` body `{enabled?, description?}` → `Intent` (admin+).
- `DELETE /api/intents/{id}` → `{ok}` (admin+).

`GET /api/projects/{id}/discovery?range=7d` → `{project, clusters, intents, coverage}`.
Cluster: `{id, key, label, status, count, affected_users, evidence[{conversation_id, excerpt, reason}], members[], detector_version}`.
Coverage: `{conversations_total, conversations_analyzed, messages_total, users_total, clustered, unassigned}` — messages, conversations, and users are different denominators.

- `PATCH /api/discovery/{id}` body `{status: "open"|"dismissed"}` → `{id, status}` (member+).
- `POST /api/discovery/{id}/rename` body `{label}` → `{id, label}` (member+).
- `POST /api/projects/{id}/discovery/manual` body `{label, member_conversation_ids[]}` → cluster (admin+).
- `POST /api/projects/{id}/discovery/merge` body `{source_ids[], label}` → cluster (admin+).
- `POST /api/projects/{id}/discovery/split` body `{label, member_conversation_ids[]}` → `{id, label, members, remainder_id}` (admin+).

`evidence`: `[{event_id, conversation_id, content, reason}]`.

`Span`: `{id, parent_id, name, kind, status, duration_ms, input, output}`. Nullable parent. Input/output may be strings or JSON values.

## Ingestion

`POST /v1/events` with `Authorization: Bearer <project_key>` and body `{events: Event[]}` → `{accepted, duplicates}`. Batch limit 100; event ids deduplicate within project. The key determines project; supplied project ids must never override it. Reject malformed batches atomically.

`Event`: `{id?, conversation_id, user_id?, role, content, timestamp?, trace_id?, span_id?, parent_span_id?, name?, status?, latency_ms?, tokens?, cost_usd?, model?, metadata?}`. Role is `user|assistant|tool|system`. Status is `success|error`; default success. Content is a string. Timestamp defaults to server time; event id defaults to UUID. Latency/cost/tokens are nonnegative. Metadata defaults to `{}` and may contain span input/output. Maximum content length 32,000 characters; batch body limited by API.

Analysis in this milestone is deterministic, rule-based triage, explicitly labeled in the UI. It detects evidenced user corrections/frustration, repeated user requests, and tool errors. Abandonment requires an elapsed-time criterion and must not be inferred merely because a conversation currently ends with a user message. Suggestions are reviewable text; resolving a cluster never changes a customer's agent.

## Phase 2: accounts and durable ingestion

Session auth: `Authorization: Bearer tvs_...` on `/api/*`. Ingest auth:
`Authorization: Bearer tvk_...` on `/v1/*`. Ingest keys return 401 on
dashboard routes; sessions return 404 on projects outside their orgs.

- `POST /api/auth/signup` body `{email, password, name?}` → `{account, organization, session}`.
- `POST /api/auth/login` body `{email, password}` → `{account, session}`.
- `POST /api/auth/logout` → `{ok}`. `GET /api/me` → `{account, organizations}`.
- `POST /api/orgs` body `{name}` → org with owner role. `GET /api/orgs` → my orgs.
- `POST /api/orgs/{id}/members` body `{email, role}` → membership (admin+).
- `PATCH /api/orgs/{id}/members/{account_id}` body `{role}` → updated (admin+).
- `DELETE /api/orgs/{id}/members/{account_id}` → `{ok}` (admin+).
- `POST /api/orgs/{id}/projects` body `{name, environment?}` → `Project` plus one-time `credential.secret`.
- `GET /api/orgs/{id}/projects` → `Project[]` without secrets.
- `POST /api/projects/{id}/credentials` body `{name?, environment?}` → `{id, prefix, secret, environment, scope}` (secret once).
- `GET /api/projects/{id}/credentials` → credential list without secrets.
- `POST /api/credentials/{id}/revoke` → `{ok}`.
- `GET /api/jobs?project_id=...` → `{jobs, usage_events, usage_bytes, recent[]}` (no payload contents).
- `POST /api/jobs/{project_id}/{event_id}/replay` → `{ok, state}`.
- `PATCH /api/projects/{id}/capture` body `{capture_content?, redact_keys?, retention_days?}` → `{project_id, settings}`.
- `GET /api/projects/{id}/usage` → `{project_id, jobs, usage_events, usage_bytes}`.
- `GET /api/orgs/{id}/audit?limit=50` → audit entries without secrets.
- `POST /api/projects/{id}/retention/run` → `{project_id, removed_events, cutoff}`.
- `GET /api/projects/{id}/setup` → `{project, key_configured, active_credentials, events_received, conversations, last_event_at, jobs, usage_events, capture}`.
- `POST /v1/otlp/traces` with ingest key and OTLP TracesData JSON → `{accepted, duplicates}`.

Ingestion still returns `{accepted, duplicates}` per batch (max 100).
Acceptance follows a durable outbox commit; materialization, usage, and
the ClickHouse mirror happen idempotently afterwards. See `docs/phase-2.md`.

## Storage scope

SQLite is the zero-configuration local development adapter. PostgreSQL is the deployable metadata adapter. Optional ClickHouse mirrors ingested events for analytical storage; this milestone does not claim a finished distributed worker or production SaaS authentication. Document what is implemented, configured, and still pending separately.
