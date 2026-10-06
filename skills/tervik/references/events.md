# Tervik HTTP ingestion contract

`POST <TERVIK_ENDPOINT>/v1/events`

Headers: `Authorization: Bearer <project_key>` and `Content-Type: application/json`.

Body: `{ "events": [event] }`. Maximum 100 events per batch. Successful response: `{ "accepted": 1, "duplicates": 0 }`. The project key determines project ownership. Stable event IDs make retries idempotent within that project. Malformed batches are rejected atomically.

An event has:

| Field | Meaning |
|---|---|
| `id` | Stable UUID, generated before first send and preserved on retries |
| `conversation_id` | Required nonempty stable application conversation ID |
| `user_id` | Optional pseudonymous user ID |
| `role` | Required `user`, `assistant`, `tool`, or `system` |
| `content` | Required string, maximum 32,000 characters; redact before export |
| `timestamp` | ISO 8601 UTC |
| `trace_id` | Shared by one turn and its related tools |
| `span_id` | Unique operation ID |
| `parent_span_id` | Parent operation ID for nested tools |
| `name` | Operation name |
| `status` | `success` or `error` |
| `latency_ms`, `tokens`, `cost_usd` | Optional nonnegative measurements; `tokens` must be an integer; omit unknown values |
| `model` | Optional actual model name |
| `metadata` | Optional object; can contain redacted span `input` and `output` |

Identifier, user, trace, span, name, and model strings have a 200-character maximum. Timestamps require a timezone and cannot be more than five minutes in the future. Metadata must contain finite JSON values. Additional top-level event fields are rejected; application-specific attributes belong in metadata. Clients reject invalid events locally so they cannot invalidate a batch of valid events.

The portable clients use a 256 KiB maximum batch, a bounded 1,000-event/5 MiB in-memory queue, stable IDs, finite transient retries, and drop reports. Authentication failures disable export until the client is recreated with the correct key. A process crash can lose queued events; this exporter does not promise durable delivery.

Dashboard verification is separate from ingestion. List `GET /api/conversations?project_id=<project_id>&range=24h` using dashboard/admin authorization when enabled. Identify the interaction by user, time, and content, then use the returned internal `id` in `GET /api/conversations/{id}`. That dashboard ID differs from the application's source `conversation_id`; do not substitute the source ID into this route.

This local foundation supports HTTP ingestion. It does not implement a hosted OAuth MCP interface, OTLP receiver, automatic framework adapters, or production account sign-in.
