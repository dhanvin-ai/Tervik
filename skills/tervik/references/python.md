# Python

Copy `scripts/tervik_client.py` into the application's server package (for example `app/telemetry/tervik_client.py`). It uses only Python's standard library (3.9+). Do not install a guessed package from PyPI; use the `tervik` package from `packages/sdk-python` only when the project already depends on it (`import tervik` exposes the same functions).

Configure the server environment:

```text
TERVIK_PROJECT_ID=<project ID from the Connect your agent page>
TERVIK_ENDPOINT=http://127.0.0.1:8000
```

## Instrument the handler

Initialize once per process, then wrap the real handler. `existing_agent`, `existing_tools`, and the request fields below stand for the application's own code.

```python
import os
from .telemetry import tervik_client as tervik

# tervik.instrumented
tervik.init(os.environ["TERVIK_PROJECT_ID"], endpoint=os.environ.get("TERVIK_ENDPOINT"))

def handle_message(request):
    turn = tervik.begin(
        user_id=request.pseudonymous_user_id,      # stable, not an email address
        agent_name="support-agent",
        input=request.message,
        conversation_id=request.conversation_id,   # the same ID for every turn of a conversation
    )
    try:
        def lookup_order(order_id):
            with turn.tool("lookup_order", {"order_id": order_id}) as call:
                call.output = existing_tools.lookup_order(order_id)   # exceptions are recorded as failures and re-raised
                return call.output

        reply = existing_agent.respond(request.message, tools={"lookup_order": lookup_order})
        turn.set_property("model", reply.model)          # optional: model, tokens, cost, or any string property
        turn.end(output=reply.text)
        return reply
    except Exception as error:
        turn.end(output=f"Error: {error}", success=False)
        raise

# In the application's existing shutdown hook:
tervik.shutdown()
```

- `turn.tool(name, input)` nests a tool call under the turn; nest further with `call.tool(...)`. Use it as a context manager, or call `call.end(output, success=False)` yourself. Record the tool's real input and output: Tervik flags made-up values such as `[customer email]` and consequential actions (cancel, refund, delete, send, book, pay) the user never asked for.
- When a turn is finished elsewhere (a callback or another function), pass `interaction_id="..."` to `begin()` and later call `tervik.get_interaction("...").end(...)`.
- `tervik.track(user_id=..., input=..., output=..., conversation_id=...)` records a finished turn in one call.
- `tervik.identify(user_id, {"plan": "pro"})` attaches traits; they appear in the dashboard's users and cohort views.
- Async handlers can use the same calls: `begin`, `tool`, and `end` never block on the network. Call `flush()`/`shutdown()` outside the response path (for example `await asyncio.to_thread(tervik.shutdown)`).
- For streaming, keep the existing iterator untouched, accumulate the text as chunks pass through, and call `turn.end(output=full_text)` when the stream finishes (or `success=False` if it fails or is cancelled).
- Pass `redact=lambda body: body` to `init()` to rewrite or drop event bodies before they are queued (return `None` to drop).

Use the secret ingest key instead of the project ID with `tervik.init(api_key=os.environ["TERVIK_API_KEY"], endpoint=...)`.

## Frameworks

For OpenAI-based agents, `tervik.integrations.instrument_openai` wraps `chat.completions.create` (including streams) and records turns, usage, and requested tool calls; for LangChain/LangGraph, add `tervik.integrations.TervikCallbackHandler` to the run callbacks. These come with the `tervik` package and use the older message-level exporter (`Tervik` class, `TERVIK_API_KEY`), which the portable client also includes (`Tervik`, `span`, `with_turn`, `stream_turn`).

Re-running the skill must detect the `tervik.instrumented` marker and the existing client before editing.
