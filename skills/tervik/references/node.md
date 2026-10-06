# Node.js / TypeScript

Requires Node 18+ for native `fetch`. Copy `scripts/tervik-client.mjs` and its `scripts/tervik-client.d.mts` declaration from this skill into an appropriate server module folder. It is a dependency-free ES module. Import `Tervik` from the copied file using the project's build conventions. The repository also includes the typed workspace package `@tervik/sdk`; it is not assumed to be published.

Configure real server-side environment values:

```text
TERVIK_ENDPOINT=http://127.0.0.1:8000
TERVIK_API_KEY=<key from your Tervik project setup>
```

Adapt this pattern around the customer's existing handler. `agent`, `tools`, and the request ID below are existing application components, not sample traffic to create. Mark the instrumented handler with `// tervik.instrumented` so re-running the skill finds it instead of adding a second wrapper:

```javascript
import { Tervik } from './telemetry/tervik-client.mjs';

// tervik.instrumented
const analytics = new Tervik({
  redact(event) {
    // Replace this with the project's actual PII/credential policy.
    return JSON.parse(JSON.stringify(event).replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, '[EMAIL]'));
  },
  onDrop({ reason, count }) {
    appMetrics.increment('tervik.dropped', count, { reason });
  }
});

export async function handleConversation(request) {
  const context = {
    conversation_id: request.conversationId,
    user_id: request.pseudonymousUserId
  };
  return analytics.withTurn(context, request.message, async trace => {
    return agent.respond(request.message, {
      lookup: query => analytics.withTool(trace, 'lookup', { query }, () => tools.lookup(query))
    });
  }, { output: response => response.text });
}

// Await this from the existing graceful shutdown hook.
export async function flushTelemetryAtShutdown() {
  return analytics.shutdown();
}
```

`capture(event)` is synchronous and returns an event ID or `null` if dropped. `flush()` returns `{accepted, duplicates, dropped, pending}`. `inspect()` exposes exporter counters without payloads or credentials. A singleton per server process avoids creating an interval per request. Custom diagnostic callbacks are isolated from agent execution.

For streaming, preserve the existing iterator/stream. Wrap the actual stream with `withStream`: chunks are yielded untouched while permitted text accumulates for one assistant event. Early termination records a partial outcome; errors record the actual failure. Do not wrap a stream with `withTurn` if the promise resolves before the stream finishes: that would record the iterator rather than the response. Keep trace and parent IDs scoped to each request and pass them explicitly to tool wrappers.

```javascript
// tervik.instrumented
export async function* handleStreamingConversation(request, stream) {
  const context = { conversation_id: request.conversationId, user_id: request.pseudonymousUserId };
  yield* analytics.withStream(context, request.message, stream);
}
```

Obtain the project credential through the dashboard session flow (`POST /api/auth/login`, then `POST /api/projects/{id}/credentials`); the ingest secret is returned once and stored server-side. Re-running the skill must detect the `tervik.instrumented` marker and existing client before editing.

For serverless runtimes, use the platform's existing background/wait-until mechanism for `flush()` where supported. An unreferenced interval does not keep a Node process alive, and no exporter can guarantee delivery after the runtime freezes. Document that limit rather than delaying every customer response without agreement.
