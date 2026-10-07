---
name: tervik
description: Add Tervik analytics to an AI agent application's conversation handlers and tools, or monitor OpenCode's own chats through its plugin hooks. Use when integrating or repairing Tervik monitoring.
---

# Tervik integration

Connect the existing agent application or OpenCode runtime to Tervik. Monitoring continues in that runtime after this coding session ends.

## Choose what to monitor

If the user wants to monitor OpenCode's own conversations and tools, use [references/opencode.md](references/opencode.md) and the included plugin installer. This mode works even when the current workspace is the extracted skill folder; do not ask for an application handler. When "this agent" is ambiguous in a coding assistant, ask whether they mean OpenCode itself or an application they are building. For other coding assistants, check for a supported runtime telemetry integration before claiming support.

For a customer application, continue below.

## Find the application first

The installed or extracted `tervik` skill folder contains instructions and portable clients. It is not the application to monitor. Installing the skill does not connect the coding assistant's own chat to Tervik.

- Use the application path or repository supplied by the user. Otherwise inspect the active workspace, including application subdirectories in a monorepo, for the real conversation handler and tools.
- If the workspace contains only this skill bundle (`SKILL.md`, `references/`, `scripts/`) or the target is ambiguous, ask one focused question: "Which agent application should I connect? Open its project in this chat, or share its local folder path or repository URL." Treat this as missing target context, not an unsupported application. Do not search unrelated folders or repeatedly inspect the skill bundle.
- Once the target is available, inspect its source to determine the handler, language, tools, and streaming behavior. Do not require the user to supply function names or runtime details that can be discovered from the code. Continue the procedure in that application.
- For OpenCode itself, use the plugin recipe above. For another coding assistant, explain any missing runtime access or telemetry integration. Do not fabricate a demo application or events to claim a connection.

## Procedure

After locating the target application, follow these steps in order. If required context is missing, ask for that context and resume when it is available. If a technical step fails, explain the specific blocker and the next action needed.

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

After inspecting the target application's source, if its structure is unsupported (no identifiable server-side handler, browser-only execution, or an incompatible runtime), do not invent an integration. Explain which step failed, what was found instead, and the smallest change that would make the application supportable. A skill-only folder is a missing target, so use the application-discovery guidance above instead.
