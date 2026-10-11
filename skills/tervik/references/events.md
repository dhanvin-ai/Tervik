# Tervik HTTP ingestion contract

Use this from any server language. Send the project ID in `x-org-id` (public and write-only), or a secret ingest key as `Authorization: Bearer <key>` or `x-api-key`. Send `Content-Type: application/json`.

## 1. Start a conversation: `POST <TERVIK_ENDPOINT>/api/v1/capture-session`

```json
{"session_id": "conv-123", "user_data": {"user_id": "user-anon-42", "plan": "pro"}, "metadata": {"surface": "web"}}
```

Send once per conversation (sending again merges traits and metadata). `user_data.user_id` is required: use a stable pseudonymous ID. Other `user_data` keys are user traits; `metadata` describes the conversation. Values are strings. Optional: `timestamp` (Unix milliseconds) and `client_config`.

## 2. Record each turn and tool call: `POST <TERVIK_ENDPOINT>/api/v1/capture-event`

A turn (the user's message and the agent's reply):

```json
{"event_id": "8b1c...", "session_id": "conv-123", "primitive_name": "support-agent",
 "args": "Where is my order 1042?", "result": "It ships tomorrow.", "success": true,
 "latency": 1200, "timestamp": 1714867201000, "metadata": {"model": "gpt-4.1", "tokens": "150"}}
```

A tool call made during that turn sets `parent_id` to the turn's `event_id`; `primitive_name` is the tool name and `args`/`result` are its JSON-encoded input and output:

```json
{"event_id": "c52f...", "session_id": "conv-123", "parent_id": "8b1c...", "primitive_name": "lookup_order",
 "args": "{\"order_id\": \"1042\"}", "result": "{\"status\": \"shipped\"}", "success": true, "latency": 300,
 "timestamp": 1714867201200}
```

- Generate `event_id` (a UUID) before the first send and keep it on retries: events are idempotent per project.
- `timestamp` is when the operation started and `latency` its duration, both in milliseconds. Timestamps cannot be more than five minutes in the future.
- Use `success: false` for failures and put the real error in `result`.
- A tool call may arrive before its turn, and an event before its session; Tervik links them when the rest arrives.
- `args` and `result` hold at most 32,000 characters; metadata at most 50 string values. The metadata keys `model`, `tokens`, and `cost` fill in those columns.
- Successful responses are `{"session_id": ...}` and `{"event_id": ...}`. HTTP 401 means an unknown project ID or key, 422 an invalid body, and 429 that the plan's event allowance is used up.

## Verify

`GET <endpoint>/api/projects/{project_id}/setup` reports `events_received` and `last_received_at`. `GET /api/conversations?project_id={project_id}&range=24h` lists conversations; open one with its returned internal `id` at `GET /api/conversations/{id}` (it differs from your `session_id`). When the dashboard is protected, these reads need a dashboard session or a read API key (`x-api-key: tervik_...`), never the project ID or ingest key.

## Other ingestion paths

- `POST /v1/events` accepts message-level events (`{"events": [{"id", "conversation_id", "role", "content", ...}]}`, up to 100 per batch) with a secret ingest key. The older portable exporter uses it.
- Stacks that already emit OpenTelemetry can send OTLP TracesData JSON to `POST /v1/otlp/traces` with a secret ingest key (up to 100 spans per batch); span identity is preserved, so nested and out-of-order spans keep their relationships.
