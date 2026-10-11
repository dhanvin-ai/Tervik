# Starter agent: try connecting an agent with the Tervik skill

This is a small trip-planner agent. It runs on a local Ollama model and has three tools: `get_weather`, `convert_currency`, and `book_hotel`. It has **no Tervik code**.

Treat it as your own agent and connect it with the Tervik skill, the same way the **Connect your agent** page guides a customer. Its sibling, [`recipe-agent`](../recipe-agent), shows what a connected agent looks like when you're done.

## 1. Make it "your" agent

Copy this folder somewhere of its own, so the coding agent edits the copy and not this repository:

```bash
cp -R examples/starter-agent ~/Projects/my-agent
```

Check that it runs before Tervik is involved. You need Ollama running with `llama3.2` downloaded. Press Ctrl+D to quit.

```bash
python3 ~/Projects/my-agent/agent.py
```

## 2. Install the Tervik skill (Connect page, step 01)

Run this in the agent's folder. It installs the skill into the project for Claude Code (`.claude/skills/`), Codex, and Cursor (both `.agents/skills/`).

```bash
cd ~/Projects/my-agent && npx skills add https://github.com/dhanvin-ai/tervik/tree/ui-maritime-theme/skills/tervik -a claude-code -a codex -a cursor -y
```

The Connect page shows the shorter `npx skills add dhanvin-ai/tervik --skill tervik`. That command reads the `main` branch, which carries an older version of the skill until this branch is merged.

If you'd rather not use `npx`, copy the skill yourself:

```bash
mkdir -p ~/Projects/my-agent/.claude/skills ~/Projects/my-agent/.agents/skills && cp -R skills/tervik ~/Projects/my-agent/.claude/skills/ && cp -R skills/tervik ~/Projects/my-agent/.agents/skills/
```

## 3. Run the prompt (Connect page, step 02)

1. In Tervik, pick or create a project, then open **Connect your agent**.
2. Copy the prompt from step 02. It includes the project ID and the endpoint.
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

It marks each change with a `tervik.instrumented` comment. Review the changes before you run them.

## 4. Check the connection (Connect page, step 04)

Run the agent with the details from step 03 of the Connect page:

```bash
cd ~/Projects/my-agent && TERVIK_PROJECT_ID=<project ID> TERVIK_ENDPOINT=http://127.0.0.1:8000 python3 agent.py
```

Send it a message. Within seconds, step 04 changes from "Waiting for your agent's first event…" to **Connected**. **Open the latest conversation** shows each turn and tool call. Things to try:

| Message | What Tervik flags |
| - | - |
| `What's the weather in Berlin?` | Tool call failed (no forecast for Berlin) |
| `Convert 50 GBP to INR` | Tool call failed (no rate) |
| `hello` | Often a raw tool-call reply, or a hotel booked nobody asked for |
| `Book a hotel` without a name | Often made-up tool values, such as `[guest name]` |
| `That is wrong` / `This is frustrating` | User corrected the agent / User was frustrated |
