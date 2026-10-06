# Python

Copy `scripts/tervik_client.py` into the application's server module folder. It uses only Python's standard library and HTTP ingestion. Set server-side `TERVIK_API_KEY` and base `TERVIK_ENDPOINT`. Do not install a guessed package from PyPI. (The repository also builds the `tervik` pip package in `packages/sdk-python`; use it only when the customer project already depends on it.)

For OpenAI-based agents, prefer `tervik.integrations.instrument_openai` over manual capture: it wraps `chat.completions.create` (including streams) and records turns, usage, and requested tool calls without changing responses. For LangChain/LangGraph agents, add `tervik.integrations.TervikCallbackHandler` to the run callbacks. Both are duck-typed, idempotent, and covered by the compatibility matrix in `docs/compatibility.md`.

Create one `Tervik` instance per process. Its background exporter uses a bounded queue and finite retries. `capture()` returns a stable event ID or `None`, `flush()` returns counts, and `shutdown()` stops the background exporter and flushes remaining events. Add `on_drop` to existing metrics; the default reports only reason/count.

Adapt the actual application handler, keeping its async and streaming behavior:

```python
from .telemetry.tervik_client import Tervik

# tervik.instrumented
analytics = Tervik()

async def handle_conversation(request):
    context = {
        "conversation_id": request.conversation_id,
        "user_id": request.pseudonymous_user_id,
    }
    async def run_turn(trace):
        async def lookup(query):
            # The span context works around an await without blocking it.
            with analytics.span(trace, "tool", "lookup", {"query": query}) as span:
                result = await existing_tools.lookup(query)
                span.output = result
                return result
        return await existing_agent.respond(request.message, lookup=lookup)
    return await analytics.with_turn(
        context, request.message, run_turn, output=lambda response: response.text
    )

# Call from the application's existing shutdown path. In an async service:
# await asyncio.to_thread(analytics.shutdown)
```

Do not synchronously call network `flush()` on an async handler's response path. During a controlled verification, flush outside that path or use `asyncio.to_thread`. Add a domain-specific `redact` callback for PII and nested tool payloads: the built-in filter only covers common credential forms. Preserve the application's original errors; error spans record those actual failures.

For a streaming handler, wrap the actual iterator with `stream_turn` (sync) or `astream_turn` (async): chunks pass through untouched while permitted text accumulates for one assistant event. Early termination records a partial outcome; errors record the actual failure.

```python
# tervik.instrumented
def handle_streaming_conversation(request, chunks):
    context = {
        "conversation_id": request.conversation_id,
        "user_id": request.pseudonymous_user_id,
    }
    yield from analytics.stream_turn(context, request.message, chunks)
```

Obtain the project credential through the dashboard session flow (`POST /api/auth/login`, then `POST /api/projects/{id}/credentials`); the ingest secret is returned once and stored server-side. Re-running the skill must detect the `tervik.instrumented` marker and existing client before editing.
