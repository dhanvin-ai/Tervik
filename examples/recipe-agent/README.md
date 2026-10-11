# Recipe helper: a connected example agent

A small cooking assistant on a local Ollama model, with three tools: `search_recipes`, `convert_units`, and `add_to_shopping_list`. It's connected to Tervik the way the Tervik skill connects a customer's agent, so every message and tool call shows up in the dashboard, and failures are flagged as they happen.

In the commands below, replace `PASTE_PROJECT_ID` with your project ID. Don't type `<` or `>` around it.

## Before you start

- **Ollama with llama3.2:**

  ```bash
  brew install ollama && brew services start ollama && ollama pull llama3.2
  ```

- **The Tervik repository** at `~/Projects/tervik`. See the [main README](../../README.md#2-get-the-code-and-set-up-the-api-once).

## Run it

1. **Open Tervik.** Use the hosted dashboard at https://www.tervik.in (sign in under **Connection settings** with the administrator token). Or start Tervik locally and open http://127.0.0.1:5173:

   ```bash
   cd ~/Projects/tervik && npm run dev
   ```

2. **Get a project ID.** Create a project (**Create your first project**, or the **+** next to the project picker), open **Connect agent**, and copy the **Project ID** from step 03.

3. **Start the agent** in a new terminal window.

   With the hosted Tervik:

   ```bash
   cd ~/Projects/tervik && TERVIK_PROJECT_ID=PASTE_PROJECT_ID TERVIK_ENDPOINT=https://api.tervik.in python3 examples/recipe-agent/agent.py
   ```

   With Tervik running locally:

   ```bash
   cd ~/Projects/tervik && TERVIK_PROJECT_ID=PASTE_PROJECT_ID python3 examples/recipe-agent/agent.py
   ```

   `TERVIK_ENDPOINT` defaults to the local API, `http://127.0.0.1:8000`.

4. **Chat with it.** The **Connect agent** page turns to **Connected** within seconds, and the conversation appears under **Conversations**. Press Ctrl+D to quit.

To see failures, try:

| Message | What Tervik flags |
| - | - |
| `Convert 3 pinches to grams` | Tool call failed (there is no such conversion) |
| `What can I cook with salmon?` | Tool call failed (no recipes for salmon) |
| `That is wrong` | User corrected the agent |
| `This is frustrating` | User was frustrated |

## What connecting it changed

These are the only changes the Tervik skill made to the original agent:

1. **The client.** `tervik_client.py` is a single file with no dependencies, copied next to the agent in your own project. In this repository the agent loads it from `skills/tervik/scripts/`.
2. **Start-up.** `tervik.init(TERVIK_PROJECT_ID, endpoint=TERVIK_ENDPOINT)` runs once, and `tervik.shutdown()` runs on exit.
3. **Each message.** `respond()` begins a turn with the conversation ID and a pseudonymous user ID, and ends it with the reply. If the reply fails, it ends the turn with `success=False`.
4. **Each tool call.** `run_tool()` records the call with `turn.tool(name, args)` and ends it with the real output, or with the error.

Look for the `tervik.instrumented` comments in `agent.py`. To connect an agent of your own the same way, follow [examples/starter-agent](../starter-agent).
