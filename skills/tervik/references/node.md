# Node.js / TypeScript

Requires Node 18+ for native `fetch`. Copy `scripts/tervik-client.mjs` and its declaration file `scripts/tervik-client.d.mts` into a server module folder (for example `src/telemetry/`). It is a dependency-free ES module. Use the `@tervik/sdk` workspace package only when the project already depends on it; it exports the same functions.

Configure the server environment:

```text
TERVIK_PROJECT_ID=<project ID from the Connect your agent page>
TERVIK_ENDPOINT=http://127.0.0.1:8000
```

## Instrument the handler

Initialize once per process, then wrap the real handler. `agent`, `tools`, and the request fields stand for the application's own code. Mark the instrumented code with `// tervik.instrumented`.

```javascript
import * as tervik from './telemetry/tervik-client.mjs';

// tervik.instrumented
tervik.init(process.env.TERVIK_PROJECT_ID, { endpoint: process.env.TERVIK_ENDPOINT });

export async function handleMessage(request) {
  const turn = tervik.begin({
    userId: request.pseudonymousUserId,       // stable, not an email address
    agentName: 'support-agent',
    input: request.message,
    conversationId: request.conversationId,   // the same ID for every turn of a conversation
  });
  try {
    const reply = await agent.respond(request.message, {
      // run() records the result, or the error, and returns or rethrows it unchanged.
      lookupOrder: orderId => turn.tool('lookup_order', { orderId }).run(() => tools.lookupOrder(orderId)),
    });
    turn.setProperty('model', reply.model);   // optional: model, tokens, cost, or any property
    turn.end(reply.text);
    return reply;
  } catch (error) {
    turn.end(`Error: ${error.message}`, false);
    throw error;
  }
}

// Await this from the existing graceful shutdown hook.
export const flushTelemetry = () => tervik.shutdown();
```

- `turn.tool(name, input)` returns a tool call: use `.run(fn)`, or call `.end(output, success)` yourself; nest further with `call.tool(...)`. Record the real input and output: Tervik flags made-up values such as `[customer email]` and consequential actions (cancel, refund, delete, send, book, pay) the user never asked for.
- To finish a turn elsewhere, pass `interactionId` to `begin()` and later call `tervik.getInteraction(id)?.end(...)`.
- `tervik.track({ userId, input, output, conversationId })` records a finished turn in one call; `tervik.identify(userId, { plan: 'pro' })` attaches user traits.
- For streaming, pass the chunks through untouched, accumulate the text, and call `turn.end(fullText)` when the stream completes (`turn.end(partial, false)` if it errors or is aborted).
- `init()` options: `apiKey` (a secret ingest key from `TERVIK_API_KEY`, used instead of the project ID), `redact(body)` (rewrite or return `null` to drop), `debug`, `flushIntervalMs`.

Nothing here throws into agent code, and sending happens on an unreferenced timer, so it does not keep the process alive. For serverless runtimes, call `tervik.flush()` through the platform's wait-until mechanism; no exporter can deliver after the runtime freezes.

The module also exports the older message-level exporter (`new Tervik({ apiKey })` with `capture`, `withTurn`, `withTool`, `withStream`) for projects that already use it.

Re-running the skill must detect the `tervik.instrumented` marker and the existing client before editing.
