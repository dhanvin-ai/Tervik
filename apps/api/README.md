# Tervik API

The FastAPI service behind the dashboard. It receives agent events, checks each conversation for problems, and serves the dashboard's data. The endpoints are documented in [docs/api.md](../../docs/api.md), and at `/docs` on a running API.

From the repository root, `npm run dev` starts this API together with the dashboard. The steps below run the API on its own.

## Set up (once)

It needs Python 3.11 or newer. macOS's own `python3` is 3.9, so use Homebrew's, such as `python3.14`:

```bash
cd ~/Projects/tervik/apps/api && python3.14 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'
```

## Run

```bash
cd ~/Projects/tervik/apps/api && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Check it:

```bash
curl http://127.0.0.1:8000/api/health
```

It returns `{"status":"ok","storage":"sqlite","analysis_mode":"rule_based"}`. With a database set through `DATABASE_URL`, `storage` is `postgresql`.

## Test

```bash
cd ~/Projects/tervik/apps/api && .venv/bin/python -m pytest
```

From the repository root, `npm run test:api` runs the same tests, and `npm run check` runs every check in the repository.

## Settings

All settings are environment variables. Locally, none are needed.

| Variable | Default | What it does |
| - | - | - |
| `DATABASE_URL` | `sqlite:///./.data/tervik.db`, relative to where the API starts | The database. `postgres://` and `postgresql://` URLs select PostgreSQL; add `?sslmode=require` for Azure. Tables and new columns are created on start. |
| `TERVIK_ADMIN_TOKEN` | none | Protects every `/api/*` route except `/api/health` and the capture API. The dashboard sends it as `Authorization: Bearer`. Generate one with `openssl rand -hex 32`. |
| `TERVIK_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | The dashboard addresses allowed to call the API from a browser, separated by commas. |
| `TERVIK_DASHBOARD_URL` | `http://localhost:5173` | Where alert messages link to. |
| `TERVIK_DEMO_ENABLED` | `true`, or `false` when an admin token is set | Allows **Explore sample workspace**. |
| `TERVIK_SIGNUP_ENABLED` | `true` | Lets anyone create an account with **Sign up**. Each account gets its own workspace and sees only its projects. `false` closes sign-up. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | none | Turn on **Continue with Google**. The OAuth client's redirect URI is `<API address>/api/auth/oauth/google/callback`. |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | none | Turn on **Continue with GitHub**. The OAuth app's callback URL is `<API address>/api/auth/oauth/github/callback`. |
| `TERVIK_PUBLIC_API_URL` | the address the request came to | The API's public address, used to build those callback URLs if a proxy hides it. |
| `ANTHROPIC_API_KEY` | none | Turns on LLM intent and policy checks, and Claude in **Chat**. |
| `TERVIK_LLM_MODEL` | `claude-opus-5-5` | The Claude model for those. |
| `OPENAI_API_KEY` | none | Adds an OpenAI model to **Chat**. |
| `TERVIK_OPENAI_MODEL` | `gpt-4.1-mini` | That model. |
| `OLLAMA_HOST_URL` | `http://127.0.0.1:11434` | Where **Chat** finds local Ollama models. |
| `PORT` | `8000` | The port, in the container image only. |
| `TERVIK_MAX_BODY_BYTES` | `4194304` (4 MiB) | The largest request accepted. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | none | Email delivery for alerts. |
| `CLICKHOUSE_URL`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`, `CLICKHOUSE_DATABASE` | none | An optional event mirror. Install `.[clickhouse]` first. |

## Background jobs

Alerts and scheduled LLM classification run as separate processes from the same code:

```bash
cd ~/Projects/tervik/apps/api && .venv/bin/python -m app.jobs alerts
```

```bash
cd ~/Projects/tervik/apps/api && .venv/bin/python -m app.jobs classify
```

Add `--once` to run a single pass. Stopping either job loses nothing.

## Deploy

`Dockerfile` builds the API image and listens on `$PORT`. On every push to `main` that changes the API, GitHub Actions publishes it to `ghcr.io/dhanvin-ai/tervik-api` and deploys it to Azure Container Apps; `scripts/deploy_azure.sh` creates the Azure resources. `railway.json` is for hosting on Railway instead. [docs/deploy.md](../../docs/deploy.md) has every step, including the database and the domain.

## How it handles data

- **Who can send what.** Agents send events with the project ID (`x-org-id`), which can only add events to its project, or with a secret project key. Neither can read data or authorize dashboard routes.
- **Validation.** A batch holds 1 to 100 events. Unknown fields are rejected. Timestamps need a timezone, are stored in UTC, and can't be more than five minutes in the future.
- **Duplicates.** Events are deduplicated by project and event ID, so retries are safe. The first stored copy wins.
- **Analysis.** Rules check every conversation as its events arrive. The root [README](../../README.md#what-tervik-detects) lists what they detect. Counts use distinct affected conversations, and anonymous users don't inflate affected-user counts. Missing latency and cost values aren't estimated.
- **Date ranges** are rolling UTC windows. Daily trends cover every UTC date the window touches, so a 7-day range can show eight dates.
- **Resolving** a problem group changes only its review status. The evidence and counts stay.
- **The ClickHouse mirror** is best effort: a mirror failure doesn't fail ingestion, and there's no retry or backfill. Dashboard reads always use the SQL database.
