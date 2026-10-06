---
name: tervik
description: Add Tervik analytics to an AI agent application's real conversation handlers and tool calls, configure server-side telemetry, and verify ingestion. Use when integrating or repairing Tervik monitoring in a customer project.
---

# Tervik integration

Connect the existing agent application to Tervik. This skill configures instrumentation; the customer's running application continues exporting telemetry after this coding session ends.

## Choose the adapter

Inspect the language, package manager, actual conversation handler, streaming behavior, and tools. Preserve existing project conventions. Read [references/node.md](references/node.md) for Node/TypeScript or [references/python.md](references/python.md) for Python. Both portable clients ship with this skill; no published npm or PyPI package is required. If another stack already emits OTLP, this foundation has no OTLP receiver: explain that limitation and integrate the HTTP contract in [references/events.md](references/events.md) rather than claiming OTLP support.

Reuse existing Tervik instrumentation and update it in place. Avoid duplicate capture, an extra unrelated agent, or replacing the model/framework. Instrumenting an MCP tool server alone captures its tools; it does not capture the conversation unless the agent's actual turn handler is also instrumented.

## Configure and instrument

- Obtain a project key through the customer's Tervik project setup. Configure `TERVIK_API_KEY` and `TERVIK_ENDPOINT` in server-side local/deployment secrets. The endpoint is a base URL, such as `http://127.0.0.1:8000`; the client appends `/v1/events`. Do not put the key in a browser bundle, source control, screenshots, or diagnostic output. Ingestion keys do not grant dashboard administration.
- Use the application's stable conversation ID and a pseudonymous user ID. The key selects the project; do not accept a browser-supplied project ID as authorization. Preserve the same conversation ID across turns, and separate conversations across users. Use a per-turn trace ID and a parent span ID for tool calls.
- Copy the appropriate portable client into the customer's server code, or use `@tervik/sdk` only if it is already present in their workspace. Import it using their build conventions. Add calls around the actual handler and actual tools. Do not send invented frustration, synthetic failures, or fake conversation events as verification.
- Review what the handler and tools contain before enabling capture. Redact application-specific secrets and PII before queueing/export, using the client redaction hook. Built-in filtering covers common credential formats, not every secret. Do not capture environment dumps, arbitrary files, cookies, full request headers, or credential-bearing tool inputs.
- Preserve handler results, original exceptions, cancellation, streaming, and concurrency. Keep export off the response's critical path. Clients have bounded in-memory buffers and retries, not durable storage. Expose drop counters in the application's existing diagnostics and await shutdown flush in its existing shutdown hook. Do not install competing signal handlers or force the process to exit.

## Verify the actual integration

Run the project's existing relevant checks. Trigger one real supported agent interaction through its real application entrypoint, with a unique conversation ID when practical. Confirm the assistant response and any actual tools still work. Flush the exporter outside the critical response path.

Read the Tervik conversation page and confirm the user/assistant events, tool spans, timing, project, and pseudonymous user. For API verification, list `GET /api/conversations?project_id=<project_id>&range=24h`, identify the interaction by user/time/content, then use its returned internal `id` in `GET /api/conversations/{id}`. The dashboard's internal ID differs from the application's source `conversation_id`. The dashboard API requires a separate admin token when configured. Do not try to use the ingest key for administrator calls. If the backend cannot be reached, report instrumentation as unverified with the concrete deployment/configuration step remaining.

Report the changed files, configuration names without values, verified conversation/dashboard link, and any production restart/deployment still required. Local success does not verify the deployed application. Do not deploy, publish packages, change account settings, or rotate keys solely because this skill was installed.
