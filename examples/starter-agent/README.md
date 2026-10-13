# Starter agent: practise connecting an agent with the Tervik skill

This is a small trip-planner agent. It runs on a local Ollama model and has three tools: `get_weather`, `convert_currency`, and `book_hotel`. It has **no Tervik code**.

Treat it as your own agent and connect it with the Tervik skill, the same way the **Connect agent** page guides a customer. Its sibling, [`recipe-agent`](../recipe-agent), shows what a connected agent looks like when you're done.

In the commands below, replace the words in capitals, such as `PASTE_PROJECT_ID`, with your own values. Don't type `<` or `>` around them.

## Before you start

- **Ollama with llama3.2:**

  ```bash
  brew install ollama && brew services start ollama && ollama pull llama3.2
  ```

- **A Tervik project.** Use the hosted dashboard at https://www.tervik.in (sign in under **Connection settings** with the administrator token), or start Tervik locally with `npm run dev` and open http://127.0.0.1:5173. Choose **Create your first project**, or the **+** next to the project picker.
- **A coding agent:** Claude Code, Codex, or Cursor.
- **The Tervik repository** at `~/Projects/tervik`. See the [main README](../../README.md#2-get-the-code-and-set-up-the-api-once).

## 1. Make it "your" agent

Copy this folder somewhere of its own, so the coding agent edits the copy and not the Tervik repository. Skip this if `~/Projects/my-agent` already exists: copying again would put a second copy inside it.

```bash
cp -R ~/Projects/tervik/examples/starter-agent ~/Projects/my-agent
```

Check that it runs before Tervik is involved. Type a message such as `What's the weather in Paris?`, then press Ctrl+D to quit.

```bash
cd ~/Projects/my-agent && python3 agent.py
```

## 2. Install the Tervik skill (Connect page, step 01)

This installs the skill into the project for Claude Code (`.claude/skills/`), Codex, and Cursor (both `.agents/skills/`):

```bash
cd ~/Projects/my-agent && npx skills add dhanvin-ai/tervik --skill tervik -a claude-code -a codex -a cursor -y
```

It's the same command the Connect page shows, with the coding agents to install it for.

If you'd rather not use `npx`, copy the skill yourself:

```bash
mkdir -p ~/Projects/my-agent/.claude/skills ~/Projects/my-agent/.agents/skills && cp -R ~/Projects/tervik/skills/tervik ~/Projects/my-agent/.claude/skills/ && cp -R ~/Projects/tervik/skills/tervik ~/Projects/my-agent/.agents/skills/
```

## 3. Run the prompt (Connect page, step 02)

1. In Tervik, pick your project and open **Connect agent**.
2. In step 02, choose **Copy**. The prompt includes the project ID and the endpoint.
3. Open `~/Projects/my-agent` in your coding agent and paste the prompt:
   - **Claude Code** (desktop app, Code tab): start a new session in that folder.
   - **Codex** (app): open that folder as the workspace.
   - **Cursor**: open that folder, then use Agent mode.

The skill should:

- add the one-file client `tervik_client.py`;
- call `tervik.init(...)` once at start-up;
- wrap `respond()` in `begin()` and `end()`;
- record each tool call in `run_tool()`;
- call `shutdown()` on exit.

It marks each change with a `tervik.instrumented` comment. Review the changes before you run them. To check that the skill did its part:

```bash
cd ~/Projects/my-agent && ls tervik_client.py && grep -n "tervik.instrumented" agent.py
```

## 4. Check the connection (Connect page, step 04)

In step 03 of the Connect page, copy the **Project ID** with the copy button next to it. Then run the agent, replacing `PASTE_PROJECT_ID` with it.

With the hosted Tervik:

```bash
cd ~/Projects/my-agent && TERVIK_PROJECT_ID=PASTE_PROJECT_ID TERVIK_ENDPOINT=https://api.tervik.in python3 agent.py
```

With Tervik running locally:

```bash
cd ~/Projects/my-agent && TERVIK_PROJECT_ID=PASTE_PROJECT_ID TERVIK_ENDPOINT=http://127.0.0.1:8000 python3 agent.py
```

A project ID looks like `3f2b8c1e-7a4d-4e8a-9c1f-2b6d5e8a1c90`, so the start of the command reads `TERVIK_PROJECT_ID=3f2b8c1e-7a4d-4e8a-9c1f-2b6d5e8a1c90 TERVIK_ENDPOINT=...`.

Send it a message. Within seconds, step 04 changes from "Waiting for your agent's first event…" to **Connected**. **Open the latest conversation** shows each turn and tool call, and the overview counts the problems. Press Ctrl+D to quit, which also sends any queued events.

Things to try:

| Message | What Tervik flags |
| - | - |
| `What's the weather in Berlin?` | Tool call failed (no forecast for Berlin) |
| `Convert 50 GBP to INR` | Tool call failed (no rate) |
| `hello` | Often a raw tool-call reply, or a hotel booked nobody asked for |
| `Book a hotel` without a name | Often made-up tool values, such as `[guest name]` |
| `That is wrong` / `This is frustrating` | User corrected the agent / User was frustrated |

## If something goes wrong

| You see | Fix |
| - | - |
| `zsh: no such file or directory: project` | The placeholder was left in the command. Replace `PASTE_PROJECT_ID` (or `<project ID>`) with the real ID, without `<` `>`. |
| `Set TERVIK_PROJECT_ID to the project ID…` | `TERVIK_PROJECT_ID=...` is missing from the start of the command. |
| `Connection refused` when you send a message | Ollama isn't running: `brew services start ollama`, then `ollama list` should show `llama3.2`. |
| Step 04 stays on "Waiting…" | Check that the endpoint matches the dashboard you're looking at: `https://api.tervik.in` for www.tervik.in, `http://127.0.0.1:8000` for the local one. Check that the project ID belongs to the project that's open. |
| `ModuleNotFoundError: tervik_client` | The skill didn't add the client. Run step 3 again, or copy `~/Projects/tervik/skills/tervik/scripts/tervik_client.py` into `~/Projects/my-agent`. |
