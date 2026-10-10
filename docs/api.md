# Tervik API

Tervik works the way Agnost AI does: you send each conversation's sessions and
events, and Tervik finds silent failures, groups them, classifies intents and
policy violations, and alerts you when something changes.

The API listens on `http://127.0.0.1:8000` locally. Every range parameter
accepts `1h`, `24h`, `7d`, `30d`, `90d`, or `all` unless noted otherwise.

## Send data

### Authentication for ingestion

| Header | Value | Notes |
| - | - | - |
| `x-org-id` | the project ID | A public, write-only routing ID. It can add events but never read them. Turn it off per project with `PATCH /api/projects/{id}/capture {"public_ingest": false}`. |
| `Authorization: Bearer` or `x-api-key` | a project ingest key (`tvk_…`) | A secret that can only write. |

### `POST /api/v1/capture-session`

Start a conversation once and reuse its `session_id` on every event.

```json
{
  "session_id": "a3f9c182-7d4e-4b6a-9e21-c5d8f0b4e731",
  "user_data": {"user_id": "user-anon-002", "plan": "pro"},
  "metadata": {"language": "en", "surface": "web"},
  "timestamp": 1714867200000,
  "client_config": "my-app/1.4"
}
```

`user_data.user_id` is required. Send a stable, pseudonymous ID rather than
an email address. The other keys become user traits. Sending the same
session again merges its traits and metadata.

### `POST /api/v1/capture-event`

Record one turn pair (the user's input and the agent's output) or one tool call.

```json
{
  "event_id": "e8b1c52f-3a9d-4e7c-8f0b-2d6a91c4ef58",
  "session_id": "a3f9c182-7d4e-4b6a-9e21-c5d8f0b4e731",
  "primitive_name": "support-agent",
  "args": "Where is my order?",
  "result": "It ships tomorrow.",
  "success": true,
  "latency": 1200,
  "timestamp": 1714867201000,
  "metadata": {"model": "gpt-4.1", "tokens": "150", "cost": "0.002"}
}
```

- For a tool call, set `parent_id` to the turn's `event_id` (or to a parent
  tool's). `primitive_name` is then the tool name, and `args` and `result`
  are its input and output, JSON-encoded if needed.
- `latency` and `timestamp` are in milliseconds.
- The metadata keys `model`, `tokens`, and `cost` (or `cost_usd`) fill in the
  model, token, and cost columns.
- Events are idempotent by `event_id`.
- A tool call sent before its parent joins the parent's trace once the
  parent arrives. Events sent before their session pick up the user when the
  session arrives.
- A turn pair counts as one event toward the plan's usage.

The older message-level endpoints `POST /v1/events` and
`POST /v1/otlp/traces` still work.

### SDKs

Both SDKs send in the background and never raise into agent code.

```python
import tervik

tervik.init("your-project-id", endpoint="http://127.0.0.1:8000")
tervik.identify("user-42", {"plan": "pro"})

turn = tervik.begin(user_id="user-42", agent_name="support", input="Where is my order?")
with turn.tool("orders.lookup", {"order_id": 42}) as call:
    call.output = lookup(42)
turn.set_property("model", "gpt-4.1")
turn.end(output="It ships tomorrow.")          # or turn.end(output="...", success=False)

tervik.track(user_id="user-42", input="Thanks", output="Anytime!", conversation_id=turn.conversation_id)
tervik.shutdown()
```

```ts
import * as tervik from '@tervik/sdk';

tervik.init('your-project-id', { endpoint: 'http://127.0.0.1:8000' });
const turn = tervik.begin({ userId: 'user-42', agentName: 'support', input: 'Where is my order?' });
const order = await turn.tool('orders.lookup', { orderId: 42 }).run(() => lookup(42));
turn.end('It ships tomorrow.');
await tervik.shutdown();
```

## Read analytics

Dashboard routes accept a dashboard session (`Authorization: Bearer tvs_…`),
the operator's administrator token, or a read API key.

### Read API keys

`POST /api/projects/{id}/api-keys {"name": "reporting"}` returns a
`tervik_<64 hex>` secret once. Send it as `x-api-key`. The key can read that
project's analytics and run classification. It cannot read secrets or ingest
keys, change settings, or reach other projects. List keys with
`GET /api/projects/{id}/api-keys`. Revoke one with `DELETE /api/api-keys/{key_id}`.

### Endpoints

| Endpoint | What it returns |
| - | - |
| `GET /api/projects/{id}/summary?range=` | Calls (agent turns and tool calls), conversations, active users, errors, success rate, average and p95 latency, tokens, cost, an hourly or daily timeline, and calls per agent |
| `GET /api/projects/{id}/tools?range=` | Per tool: calls, errors, success rate, latency (average, p50, p95), conversations, users, a timeline, and its most common errors. Also the error share across tools |
| `GET /api/projects/{id}/events` | The event log, filtered by `role`, `status`, `name`, `user_id`, `conversation_id` (or session ID), `search`, `event_type` (`turn`, `tool_call`, `message`), and `metadata_key`/`metadata_value`. Supports `sort` and `page`/`page_size` |
| `GET /api/projects/{id}/events/export` | The same filters as a CSV download. Cells that start with a formula character are escaped |
| `GET /api/projects/{id}/events/{event_id}` | One event in full, with its other turn half, parent, child tool calls, and session |
| `GET /api/projects/{id}/errors?range=` | Failed operations, counts per tool or agent, and grouped error messages |
| `GET /api/projects/{id}/metadata?range=&key=` | Metadata keys from events, sessions, and user traits. With `key`, its values with conversation counts |
| `GET /api/projects/{id}/users?range=&search=&sort=` | End users with their traits, conversations, errors, and problem labels |
| `GET /api/projects/{id}/groups?key=plan` | Conversations grouped by any metadata key or user trait, with users, messages, and problems per group |
| `GET /api/projects/{id}/search?q=` | Messages containing the text, with snippets |
| `GET /api/overview`, `/api/clusters`, `/api/conversations` | The dashboard's existing views. Conversation detail now includes the session and the user's traits |

## Intents and policies

- **Intents** say what a user is trying to accomplish:
  `POST /api/projects/{id}/intents {"name", "description", "examples"}`.
  An intent needs a description or at least one example.
- **Policies** (SOPs) are rules the agent must follow:
  `POST /api/projects/{id}/policies {"title", "description", "severity"}`.
  Edit one with `PATCH /api/policies/{policy_id}` and remove it with
  `DELETE /api/policies/{policy_id}`. Rewording a policy makes Tervik check
  conversations against it again.
- **Classification:** `POST /api/projects/{id}/classify {"range", "limit", "offset", "force"}`
  reviews conversations that changed since their last review.
  - With `ANTHROPIC_API_KEY` set, one structured LLM call per conversation
    records matching intents, policy violations, and a suggested intent when
    nothing configured fits. Every finding must cite messages in the
    transcript; anything it cannot cite is dropped.
  - Without a key, intents fall back to example matching and policies are
    reported as not checked.
  - `GET /api/projects/{id}/classify/status` reports progress.
- **Results:**
  - `GET /api/projects/{id}/intent-stats?range=` returns each intent's share
    of analyzed conversations, its trend and timeline, and suggested intents.
  - `GET /api/projects/{id}/violations?range=` returns each policy's
    violations and rate.
  - `GET /api/projects/{id}/evidence?kind=intent|policy|suggested&target_id=|label=`
    returns the cited messages with the session and user.
  - Policy violations also appear in the problem list as
    "A policy was not followed · <policy>".
- **LLM helpers:** `POST /api/projects/{id}/intents/suggest` proposes intents
  from recent opening messages. `POST /api/projects/{id}/intents/enrich`
  writes a description and examples for one intent.

## Alerts

`POST /api/projects/{id}/alerts` creates a rule. Every rule has a `kind`, a
`metric` with an optional `target`, a `threshold`, a `window_hours`, a
`cooldown_hours`, and `channels`.

**Kinds**

- `threshold` fires when the metric reaches the threshold.
- `trend` fires when the metric rises by the threshold percentage over the
  previous window.
- `summary` sends a daily message.

**Metrics**

| Metric | What it counts |
| - | - |
| `problems` (default) | Flagged conversations, optionally of one `signal_kind` |
| `intent` | Conversations with the intent in `target` |
| `violation` | Conversations that broke the policy in `target` |
| `tool_errors` | Failed tool calls, optionally of the tool named in `target` |
| `error_rate` | Percent of operations that failed |
| `conversations` | Conversation volume |
| `suggested_intents` | Summaries only: users asking for things no intent covers |

**Channels:** `webhook`, `email` (SMTP settings), and `slack` (an incoming
webhook URL).

Messages name the intent, policy, or tool and list up to five recent example
conversations. When `TERVIK_DASHBOARD_URL` is set, they link back to the
dashboard.

**Other alert endpoints**

| Endpoint | What it does |
| - | - |
| `POST /api/projects/{id}/alerts/slack {"webhook_url"}` | Turns on the daily summary and the new-intents summary in one Slack channel |
| `POST /api/alerts/{alert_id}/test` | Sends the current message to every channel now, without recording a delivery |
| `GET /api/alerts/{alert_id}/history` | Lists the alert's deliveries |

## Plans

`GET /api/plans` lists the tiers.

| Tier | Events per rolling 30 days | Retention |
| - | - | - |
| free | 1,000 | 7 days |
| starter | 10,000 | 30 days |
| pro | 1,000,000 | 90 days |
| beta (default) | 100,000 | 90 days |
| enterprise | 100,000,000 | 365 days |

- Ingestion returns HTTP 429 once an organization reaches its allowance.
- A project's retention never exceeds its plan's.
- `GET /api/orgs/{id}/billing` shows usage.
- `PUT /api/orgs/{id}/plan {"name"}` changes the plan. Billing is not wired
  up, so with an administrator token set, only the operator can change
  plans. Without one (local development), the organization's owner can.

## Hosted MCP server

`POST /mcp` speaks JSON-RPC to MCP clients and requires a dashboard session.
Every tool is scoped to the caller's organizations, and every call is audited.

| Area | Tools |
| - | - |
| Conversations and problems | `tervik_list_conversations`, `tervik_get_conversation`, `tervik_list_clusters`, `tervik_get_cluster` |
| Usage and reliability | `tervik_summary`, `tervik_tool_stats`, `tervik_list_errors` |
| Intents and policies | `tervik_list_intents`, `tervik_intent_stats`, `tervik_list_violations` |
| Search | `tervik_search` |
| Improvements and operations | `tervik_get_improvement`, `tervik_ops_summary` |

## Background jobs

| Command | What it does |
| - | - |
| `python -m app.jobs alerts` | Evaluates alert rules and sends deliveries |
| `python -m app.jobs classify` | Reviews new and changed conversations |

Both run from `apps/api` or the API image, and Docker Compose runs both. Add
`--once` for a single pass. From the repository root, `python workers/alert.py`
and `python workers/classify.py` do the same.

## Configuration

| Variable | Purpose |
| - | - |
| `ANTHROPIC_API_KEY` | Turns on LLM classification, intent suggestions, and policy checks |
| `TERVIK_LLM_MODEL` | Classification model (default `claude-opus-5-5`; a smaller model costs less per conversation) |
| `TERVIK_LLM_BASE_URL` | The Anthropic API base URL |
| `TERVIK_DASHBOARD_URL` | The dashboard link in alert messages |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Email alerts |
