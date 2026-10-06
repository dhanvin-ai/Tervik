# Tervik

Skill-installed analytics for AI agents. Find failures. Build better agents.

Tervik's first phase is a runnable local foundation: create a project, send real agent events, inspect conversations and tool spans, and review evidence from deterministic failure rules. The downloadable skill helps a coding agent add that instrumentation to an existing application.

## Start locally

Requirements: Node.js 22.12+ and Python 3.11+. Run these from this repository:

```sh
npm ci
npm run setup:api
npm run dev
```

Open [the dashboard](http://127.0.0.1:5173). Create a project to start with an empty workspace, or choose **Load sample workspace** for clearly labeled sample conversations. The local API runs at `http://127.0.0.1:8000`; its database is persisted under `.data/` and ignored by Git. API documentation is available at `http://127.0.0.1:8000/docs`.

Local developer mode has no account login and binds to loopback. To protect dashboard routes, set `TERVIK_ADMIN_TOKEN` in `.env` and enter it in the dashboard's access settings. A project ingestion key cannot authorize dashboard routes. Do not expose developer mode to the internet.

## Connect an agent

In the dashboard's **Integration** page, retrieve the project key and endpoint. Set `TERVIK_API_KEY` and `TERVIK_ENDPOINT` in the monitored application's server environment. Install the skill:

```sh
npx skills add dhanvin-ai/tervik --skill tervik
```

Then ask your coding agent:

> Use the tervik skill to add Tervik analytics to this agent.

The repository is currently private, so GitHub installation requires authenticated access to `dhanvin-ai/tervik`. The dashboard also offers a self-contained skill ZIP. Extract its `tervik` folder into your coding agent's skill directory. The skill includes portable Node.js and Python clients; it does not depend on an unpublished npm package. `@tervik/sdk` is a buildable workspace package, not yet published to npm.

Instrumentation runs in your application's server process after setup. It records real turns and tool calls, uses stable event IDs across delivery retries, and reports dropped telemetry. Queues are bounded and held in memory; flushing on an existing shutdown path is important. Common-secret filtering is best effort. Configure application-specific redaction before sending sensitive content.

## Run containers

The container setup runs the web app, FastAPI, PostgreSQL, and a ClickHouse event mirror. It binds its published ports to loopback and requires an administrator token.

```sh
python3 scripts/configure_docker.py
docker compose --env-file .env.docker up --build -d
```

Open `http://127.0.0.1:4173`. Enter `TERVIK_ADMIN_TOKEN` from the ignored `.env.docker` file in the dashboard access dialog. API access is at `http://127.0.0.1:8001`; the web app also proxies ingestion at `/v1/events`. Demo loading is disabled by default in this setup. To enable it deliberately, set `TERVIK_DEMO_ENABLED=true` in `.env.docker` and recreate the API container.

```sh
docker compose --env-file .env.docker down
```

Stopping containers preserves data volumes. SQLite is the development adapter; PostgreSQL stores the same foundation records in containers. ClickHouse mirrors accepted events asynchronously on a best-effort basis. Dashboard queries still use the SQL database. A durable mirror outbox, background analysis workers, and analytical queries in ClickHouse belong to the next infrastructure milestone.

## Verify

```sh
npm run check
```

This runs TypeScript checks, the web/SDK build, SDK tests, API tests, and an end-to-end SDK → API test with isolated temporary storage. The smoke test also restarts the API to verify persistence, checks key separation, and confirms project-scoped deduplication. CI runs these checks on pushes and pull requests.

With the container stack already running, `npm run test:containers` verifies PostgreSQL and the ClickHouse mirror and removes only the records it creates.

## Phase boundaries

See [Phase 1 acceptance](docs/phase-1.md), [the architecture](docs/architecture.md), and [the API contract](docs/api-contract.md).

The current rules detect explicit corrections, frustration phrases, repeated requests, and reported tool errors. They are triage signals that require review. Groups are rule categories, not semantic clusters. Resolving a group changes its review status; it does not edit or deploy the customer's agent. Semantic clustering, account authentication and organizations, durable queue workers, alerts, regression evaluation, automated fixes, billing, and hosted MCP access are planned for later phases.
