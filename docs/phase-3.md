# Phase 3: first SDK, skill, and investigation interface

Implements section 6 of the saved roadmap on top of the Phase 2 foundation.
TypeScript is the first SDK (the language the dashboard and skill target
first); Python follows in Phase 4.

## What was built

- `Tervik.withStream` (SDK, portable client, typings): wraps an actual
  async iterator. Chunks are yielded untouched while permitted text
  accumulates for one assistant event. Early termination records a partial
  outcome (`stream_cancelled`); mid-stream errors record the actual failure
  and rethrow the original. Telemetry never throws.
- Python `stream_turn` / `astream_turn`: sync and async generator wrappers
  with the same contract, including `GeneratorExit` handling for abandoned
  streams.
- Skill 9-step procedure (`skills/tervik/SKILL.md`): inspect, detect
  existing instrumentation (`tervik.instrumented` marker, no duplicate
  wrappers), authenticate + select org/project, choose a recipe, edit,
  run/deploy, trigger a real interaction, verify via setup status and
  conversation evidence, report. Unsupported applications get an
  explanation, not an invented integration.
- Recipe updates: session-based credential flow, streaming wrappers, OTLP
  receiver documented in `events.md` (the old "no OTLP receiver" note is
  removed).
- `GET /api/projects/{id}/setup`: connection/setup status (key configured,
  active credentials, events, conversations, last event, job breakdown,
  usage, capture summary). Ingest keys get 401; other orgs get 404.
- Dashboard: account-session login in connection settings, setup-status and
  ingestion-diagnostics card on the integration page. The conversation
  explorer (messages/trace tabs, nested spans, tool input/output) and
  failure-cluster evidence views carry over from the foundation.

## Completion gate

- A new customer completes the two-step install (`npx skills add
  dhanvin-ai/tervik --skill tervik`, then the setup prompt) and inspects a
  real conversation without assistance: covered by the extended
  `scripts/smoke.mjs` (SDK capture + streaming → durable ingestion →
  setup status → overview/clusters/conversation detail with nested spans →
  restart durability).
- Re-running the skill adds no duplicate wrappers: the skill requires
  detecting the `tervik.instrumented` marker and existing clients before
  editing; the SDK test `the downloadable dependency-free client
  instruments an existing handler` pins single-capture behavior.

## Test record

- API: 40 passed (30 Phase 1 + 8 Phase 2 + 2 Phase 3 setup-status).
- SDK: 11 passed (9 existing + 2 streaming). Python clients: 7 passed.
- Schema: 10 passed. `node scripts/smoke.mjs`: both passes.
