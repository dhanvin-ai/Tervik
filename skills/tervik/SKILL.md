---
name: tervik
description: Add Tervik analytics to an AI agent application's conversation handlers and tools, or monitor OpenCode's own chats through its plugin hooks. Use when integrating or repairing Tervik monitoring.
---

# Tervik integration

Connect the existing agent application, or the OpenCode runtime, to Tervik. Tervik records each user message and the agent's reply as one turn, with the agent's tool calls nested under it, then flags silent failures: corrections, frustration, failed or timed-out tools, made-up tool values, actions nobody asked for, and claims no tool backed. This skill adds the instrumentation; monitoring continues in that runtime after this coding session ends.

## Choose what to monitor

If the user wants to monitor OpenCode's own conversations and tools, use [references/opencode.md](references/opencode.md) and the included plugin installer. This mode works even when the current workspace is the extracted skill folder; do not ask for an application handler. When running in OpenCode from a skill-only workspace, a request to add analytics to "this agent" refers to OpenCode itself unless the user supplies another application target. Select the OpenCode recipe before searching for an application handler. In other ambiguous workspaces, ask which target they mean. For other coding assistants, check for a supported runtime telemetry integration before claiming support.

For OpenCode monitoring, check for an already-installed plugin and configured destination first. If new events are arriving, report the existing connection and verify the current interaction; do not say setup is blocked because the skill folder has no handler. An earlier reply in the chat may have used older application-only guidance, so use the current OpenCode recipe.

For a customer application, continue below.

## Find the application first

The installed or extracted `tervik` skill folder contains instructions and portable clients. It is not the application to monitor. Installing the skill does not connect the coding assistant's own chat to Tervik.

- Use the application path or repository supplied by the user. Otherwise inspect the active workspace, including application subdirectories in a monorepo, for the real conversation handler and tools.
- If the workspace contains only this skill bundle (`SKILL.md`, `references/`, `scripts/`) or the target is ambiguous, ask one focused question: "Which agent application should I connect? Open its project in this chat, or share its local folder path or repository URL." Treat this as missing target context, not an unsupported application. Do not search unrelated folders or repeatedly inspect the skill bundle.
- Once the target is available, inspect its source to determine the handler, language, tools, and streaming behavior. Do not require the user to supply function names or runtime details that can be discovered from the code. Continue the procedure in that application.
- For OpenCode itself, use the plugin recipe above. For another coding assistant, explain any missing runtime access or telemetry integration. Do not fabricate a demo application or events to claim a connection.

## Procedure

After locating the target application, follow these steps in order. If required context is missing, ask for that context and resume when it is available. If a technical step fails, explain the specific blocker and the next action needed.

1. Inspect the customer's repository and identify the actual agent entrypoint: the real conversation handler (where a user message comes in and the agent's reply goes out), its streaming behavior, and its real tools. Preserve existing project conventions.
2. Detect existing instrumentation. Search for `tervik`, `TERVIK_PROJECT_ID`, `TERVIK_API_KEY`, and the `tervik.instrumented` marker. When instrumentation already exists, reuse it in place and update it; re-running this skill must add no duplicate clients, wrappers, or capture calls. Instrumenting an MCP tool server alone captures its tools, not the conversation, unless the agent's turn handler is also instrumented.
3. Get the project's connection details. The user copies them from the Tervik dashboard's **Connect your agent** page, and the setup prompt usually includes them: the **project ID** and the **endpoint** (for local development, `http://127.0.0.1:8000`). If either is missing, ask the user for it; do not guess or create a project. The project ID is a public, write-only routing identifier: it can add events to that project but never read them. If the project has public ingestion turned off, use a secret ingest key in `TERVIK_API_KEY` instead (shown on the same page); keep that key out of source control, prompts, and browser code.
4. Choose the recipe for the stack: [references/python.md](references/python.md) for Python, [references/node.md](references/node.md) for Node/TypeScript, or [references/events.md](references/events.md) for any other server language (two HTTP endpoints). Both portable clients ship with this skill in `scripts/`; no published package is required. Stacks that already export OpenTelemetry spans can send them to `POST /v1/otlp/traces` instead (see events.md).
5. Modify the application code and configuration. Copy the portable client into the server code (or use the `tervik` / `@tervik/sdk` package only if the project already depends on it). Initialize once at startup with `TERVIK_PROJECT_ID` and `TERVIK_ENDPOINT`. In the real handler, `begin()` an interaction for each user message with the application's stable conversation ID and a pseudonymous user ID, record each real tool call under it with `turn.tool(name, input)` and end it with the actual output and success, then `end()` the interaction with the actual reply (or `success=False` on failure). Mark instrumented code with a `tervik.instrumented` comment so re-runs find it. Do not send invented frustration, synthetic failures, or fake conversation events as verification.
6. Configure `TERVIK_PROJECT_ID` and `TERVIK_ENDPOINT` (or `TERVIK_API_KEY`) in the server's local and deployment environment, following the project's existing configuration pattern. Flush on the application's existing shutdown hook.
7. Trigger a real interaction through the real application entrypoint: send one ordinary message, preferably one that uses a tool. Reuse the same conversation ID across that conversation's turns.
8. Confirm the turn and its tool calls reached Tervik. The dashboard's **Connect your agent** page turns to **Connected** within seconds and links to the conversation. Programmatically, `GET /api/projects/{project_id}/setup` reports `events_received` and `last_received_at`; then `GET /api/conversations?project_id={project_id}&range=24h` lists the conversation, and its returned internal `id` opens `GET /api/conversations/{id}` with the messages, tool calls, timing, and any problems found. The internal ID differs from the application's own conversation ID. If the backend cannot be reached, report the instrumentation as unverified and name the remaining configuration or deployment step.
9. Report the changed files, the configuration names (without secret values), the verified conversation or dashboard link, and any restart or deployment still required. Local success does not verify a deployed application. Do not deploy, publish packages, change account settings, or rotate keys because this skill was installed.

## Capture policy

- Review what the handler and tools contain before enabling capture. Send a stable pseudonymous user ID, not an email address. Redact application-specific secrets and PII with the client's redaction hook before export; built-in filtering covers common credential formats only. Do not capture environment dumps, arbitrary files, cookies, full request headers, or credential-bearing tool inputs.
- Preserve handler results, original exceptions, cancellation, streaming, and concurrency. Telemetry is sent from a background thread or timer, off the response path, from a bounded in-memory queue with finite retries; it never raises into agent code and does not promise durable delivery. Flush in the existing shutdown hook; do not install competing signal handlers or force the process to exit.

## Unsupported applications

After inspecting the target application's source, if its structure is unsupported (no identifiable server-side handler, browser-only execution, or an incompatible runtime), do not invent an integration. Explain which step failed, what was found instead, and the smallest change that would make the application supportable. A skill-only folder is a missing target, so use the application-discovery guidance above instead.
