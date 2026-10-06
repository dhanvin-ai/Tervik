# Tervik Python SDK

Server-side conversation and tool telemetry for Tervik. Standard library
only; framework integrations are duck-typed and never require the
framework to be installed.

```python
from tervik import Tervik

analytics = Tervik()  # TERVIK_API_KEY + TERVIK_ENDPOINT from the environment

async def handle(request):
    return await analytics.with_turn(
        {"conversation_id": request.conversation_id, "user_id": request.user_id},
        request.message, run_turn,
    )
```

Framework integrations live in `tervik.integrations` (`openai`, `langchain`).
See `docs/compatibility.md` for the versioned support matrix.
