# Recipe helper: a connected example agent

A small cooking assistant on a local Ollama model, with three tools: `search_recipes`, `convert_units`, and `add_to_shopping_list`. It is connected to Tervik the way the Tervik skill connects a customer's agent, so every message and tool call shows up in the dashboard, and failures are flagged as they happen.

## Run it

Ollama needs to be running, with `llama3.2` downloaded (`ollama pull llama3.2`). Then:

1. Start Tervik with `npm run dev`.
2. In the dashboard, create a project (the **+** next to the project picker), open **Connect your agent**, and copy the project ID.
3. Start the agent:

```bash
TERVIK_PROJECT_ID=<project ID> python3 examples/recipe-agent/agent.py
```

Chat with it. The **Connect your agent** page turns to **Connected** within seconds, and the conversation appears under **Conversations**.

To see failures, try:

| Message | What Tervik flags |
| - | - |
| `Convert 3 pinches to grams` | Tool call failed (there is no such conversion) |
| `What can I cook with salmon?` | Tool call failed (no recipes for salmon) |
| `That is wrong` | User corrected the agent |
| `This is frustrating` | User was frustrated |

## What connecting it changed

These are the only changes the Tervik skill made to the original agent:

1. **The client.** `tervik_client.py` was copied next to the agent. It is a single file with no dependencies.
2. **Start-up.** `tervik.init(TERVIK_PROJECT_ID, endpoint=TERVIK_ENDPOINT)` runs once, and `tervik.shutdown()` runs on exit.
3. **Each message.** `respond()` begins a turn with the conversation ID and a pseudonymous user ID, and ends it with the reply. If the reply fails, it ends the turn with `success=False`.
4. **Each tool call.** `run_tool()` records the call with `turn.tool(name, args)` and ends it with the real output, or with the error.

Look for the `tervik.instrumented` comments in `agent.py`.
