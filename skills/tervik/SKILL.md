---
name: tervik
description: Add Tervik analytics to an AI agent application's real conversation handlers and tool calls, configure server-side telemetry, and verify ingestion. Use when integrating or repairing Tervik monitoring in a customer project.
---

# Tervik integration

Connect the existing agent application to Tervik. This skill configures instrumentation; the customer's running application continues exporting telemetry after this coding session ends.

## Procedure

Follow these steps in order. Stop and explain when a step cannot be completed.

1. Inspect the customer's repository and identify the actual agent entrypoint: the real conversation handler, its streaming behavior, and its real tools. Preserve existing project conventions.
2. Detect existing instrumentation. Search for `tervik`, `TERVIK_API_KEY`, and the `tervik.instrumented` marker. When instrumentation already exists, reuse it in place and update it; re-running this skill must add no duplicate wrappers, clients, or capture calls. Instrumenting an MCP tool server alone captures its tools; it does not capture the conversation unless the agent's actual turn handler is also instrumented.
3. Authenticate and select the correct organization and project. Log in with a dashboard session (`POST /api/auth/login`), list organizations (`GET /api/orgs`), and select or create the project (`GET /api/orgs/{id}/projects`, `POST /api/orgs/{id}/projects`). Create a scoped ingest credential for the project's environment (`POST /api/projects/{id}/credentials`); the secret is returned once. The key selects the project; do not accept a browser-supplied project ID as authorization.
4. Choose a supported integration recipe. Read [references/node.md](references/node.md) for Node/TypeScript or [references/python.md](references/python.md) for Python. Both portable clients ship with this skill; no published npm or PyPI package is required. If another stack already emits OTLP, send spans to `POST /v1/otlp/traces`; otherwise integrate the HTTP contract in [references/events.md](references/events.md) rather than claiming OTLP support.
5. Modify the relevant application code and configuration. Copy the appropriate portable client into the customer's server code, or use `@tervik/sdk` only if it is already present in their workspace. Import it using their build conventions. Mark instrumented entrypoints with a `tervik.instrumented` comment so re-runs can find them. Add calls around the actual handler and actual tools. Do not send invented frustration, synthetic failures, or fake conversation events as verification.
6. Run the application or identify the required deployment step. Configure `TERVIK_API_KEY` and `TERVIK_ENDPOINT` in server-side local/deployment secrets. The endpoint is a base URL, such as `http://127.0.0.1:8000`; the client appends `/v1/events`. Do not put the key in a browser bundle, source control, screenshots, or diagnostic output. Ingestion keys do not grant dashboard administration.
7. Trigger a real interaction through the real application entrypoint, with a unique conversation ID when practical. Use the application's stable conversation ID and a pseudonymous user ID. Preserve the same conversation ID across turns, and separate conversations across users. Use a per-turn trace ID and a parent span ID for tool calls. For streaming handlers, wrap the actual iterator with `withStream`/`stream_turn` so chunks pass through untouched while one assistant event is recorded; early termination and errors record the actual outcome.
8. Confirm the conversation and nested operations reached the platform. Check `GET /api/projects/{id}/setup` for received events and pending/failed jobs. Then list `GET /api/conversations?project_id=<project_id>&range=24h`, identify the interaction by user/time/content, and use its returned internal `id` in `GET /api/conversations/{id}` to confirm user/assistant events, tool spans, timing, project, and pseudonymous user. The dashboard's internal ID differs from the application's source `conversation_id`. Dashboard reads use the session from step 3; never use the ingest key for administrator calls. If the backend cannot be reached, report instrumentation as unverified with the concrete deployment/configuration step remaining.
9. Report the changes and dashboard link. Report the changed files, configuration names without values, verified conversation/dashboard link, drop counters from `inspect()`, and any production restart/deployment still required. Local success does not verify the deployed application. Do not deploy, publish packages, change account settings, or rotate keys solely because this skill was installed.

## Capture policy

- Review what the handler and tools contain before enabling capture. Redact application-specific secrets and PII before queueing/export, using the client redaction hook. Built-in filtering covers common credential formats, not every secret. Do not capture environment dumps, arbitrary files, cookies, full request headers, or credential-bearing tool inputs.
- Preserve handler results, original exceptions, cancellation, streaming, and concurrency. Keep export off the response's critical path. Clients have bounded in-memory buffers and retries, not durable storage. Expose drop counters in the application's existing diagnostics and await shutdown flush in its existing shutdown hook. Do not install competing signal handlers or force the process to exit.

## Unsupported applications

When the application structure is unsupported (no identifiable server-side handler, browser-only execution, or an incompatible runtime), do not invent an integration. Explain which step failed, what was found instead, and the smallest change that would make the application supportable.
