# Integration compatibility matrix

Phase 4 covers the first two agent frameworks, chosen for widest pilot
demand. Every entry passes fixture tests (normal, streaming, tool failure,
parallel, retry, shutdown) in this repository. A real customer application
test is still required per integration before it is advertised as complete.

| Framework | Supported API | Versions | Notes |
|---|---|---|---|
| OpenAI Python | `chat.completions.create` (incl. `stream=True`), `responses.create` | `openai>=1.0` (duck-typed; the package is never imported) | Records turns, token usage, model, requested tool calls; streams pass chunks through untouched |
| Anthropic Python | `messages.create` (incl. `stream=True`) | `anthropic>=0.30` (duck-typed) | Records turns, token usage, model, tool_use blocks as tool spans |
| LangChain / LangGraph | `BaseCallbackHandler` (`on_chain_*`, `on_llm_*`, `on_tool_*`) | `langchain-core>=0.1` (duck-typed) | Shared trace ids, tool-parent linkage, duplicate run delivery recorded once |
| MCP servers (instrumented) | Wrap tool handlers with `withTool`/`span` | any MCP Python/TS server | Tool telemetry flows through the normal pipeline; the turn handler must also be wrapped for conversations |
| Raw HTTP / cURL | `POST /v1/events` | events-v2 schema | Any language; stable ids make retries idempotent |
| OTLP emitters | `POST /v1/otlp/traces` (TracesData JSON) | OTLP 1.x JSON | Span identity preserved; child-before-parent kept |

## Client versions

Clients send `X-Tervik-Client: <name>/<version>` on every batch.
`GET /api/compat` advertises the minimum supported versions and the
stable event contract. Older clients keep working; upgrade at convenience.

## Rules for every integration

- Preserve usable existing telemetry: instrumenting twice (re-run skill,
  double-patch, redelivered runs) must not create duplicate event streams.
  OpenAI wrappers carry a `tervik.instrumented` marker; the LangChain
  handler keys runs by run id.
- Telemetry failures never interrupt the agent: results stream through,
  original exceptions are re-raised, callbacks are isolated.
- Historical import uses `POST /v1/events` with original timestamps and
  stable ids; relationships (trace/span/parent) are preserved and re-import
  is a no-op. Raise the project's `retention_days` first when importing
  history older than the retention window.
