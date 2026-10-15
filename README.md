# Tervik

Skill-installed analytics for AI agents. Find failures. Build better agents.

Tervik works like [Agnost AI](https://agnost.ai/). Your agent sends each conversation to Tervik: user messages, replies, and the tool calls in between. Tervik checks every conversation for problems and shows them in a dashboard:

- finds silent failures, such as failed tool calls, made-up tool values, actions nobody asked for, and frustrated users, and groups them;
- tracks tool reliability, users, and cohorts;
- classifies intents and policy violations with an LLM;
- alerts you by Slack, email, or webhook;
- answers questions from MCP clients.

| | Where |
| - | - |
| Dashboard | https://www.tervik.in |
| API | https://api.tervik.in |
| API reference | [docs/api.md](docs/api.md) |
| Hosting it yourself | [docs/deploy.md](docs/deploy.md) |

In the commands below, replace the words in capitals, such as `PASTE_PROJECT_ID`, with your own values. Don't type `<` or `>` around them: zsh reads `<` as "read from a file".

## Use the hosted Tervik

1. Open https://www.tervik.in.
2. Choose **Sign up** (top right) and create an account: with Google or GitHub when the server has them set up, or with your email and a password of at least 8 characters. You get your own workspace: the projects you create there, and their conversations, are private to it. Next time, choose **Log in**. You stay logged in on that browser until you choose **Log out** (bottom left of the dashboard).

   To see every project on the server instead, as its operator: choose **Log in**, then **Use the administrator token**, and paste the administrator token from the API's setup (on Azure, `az containerapp secret show --name tervik-api --resource-group tervik --secret-name admin-token --query value -o tsv` prints it) into **Administrator token**. It lasts until you close the tab.
3. Choose **Create your first project** and name it.
4. Open **Connect agent**. It shows the project ID and the endpoint, `https://api.tervik.in`.
5. Connect an agent: see [Connect your agent](#connect-your-agent).

## Run it on your computer

### 1. Install the requirements (once)

You need Node.js 22.12 or newer and Python 3.11 or newer. On a Mac with [Homebrew](https://brew.sh):

```bash
brew install node python@3.14 ollama
```

macOS's own `python3` is 3.9, which is too old for the API. Check what you have:

```bash
node --version && python3 --version
```

### 2. Get the code and set up the API (once)

```bash
git clone https://github.com/dhanvin-ai/tervik.git ~/Projects/tervik
```

```bash
cd ~/Projects/tervik && npm ci
```

```bash
cd ~/Projects/tervik && python3.14 scripts/setup_api.py
```

`setup_api.py` creates the API's Python environment in `apps/api/.venv`. If `python3 --version` already shows 3.11 or newer, `npm run setup:api` does the same.

### 3. Start Tervik

```bash
cd ~/Projects/tervik && npm run dev
```

This starts the API at http://127.0.0.1:8000 and the dashboard at http://127.0.0.1:5173. Open the dashboard, then choose **Create your first project**, or **Explore sample workspace** for labelled sample conversations. Press Ctrl+C to stop.

The local database is `.data/tervik.db`, which Git ignores. API documentation is at http://127.0.0.1:8000/docs. Local mode has no sign-in; don't expose it to the internet. To require a token, put `TERVIK_ADMIN_TOKEN=a-long-random-value` in `.env` and enter it in **Connection settings**.

### 4. Start a local model (for Chat and the example agents)

```bash
brew services start ollama && ollama pull llama3.2
```

`ollama pull` downloads about 2 GB once. Check that it's running:

```bash
ollama list
```

## Try it without writing code

Each of these sends conversations to Tervik, and the problems show up in the dashboard within seconds.

| Way | How | Needs |
| - | - | - |
| **Chat page** | In the dashboard, choose **Chat** and talk to the assistant. Problems appear under each reply and on the overview. | Ollama, or `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` on the API |
| **Demo agent** in the terminal | `npm run demo:agent` (a shop support agent), or `npm run demo:agent -- --persona general` (a ChatGPT-style assistant). Type `/problems` to list what Tervik found. | Ollama |
| **Scripted conversations** | `npm run try:agent` sends a set of good and bad conversations, then prints a summary. | Nothing |
| **Recipe agent**, already connected | See [examples/recipe-agent](examples/recipe-agent). | Ollama |
| **Your Codex sessions** | `npm run import:codex -- --watch` sends each Codex turn as it finishes. | Codex on this computer |
| **Your ChatGPT history** | In ChatGPT, choose **Settings → Data controls → Export data**, then `npm run import:chatgpt -- ~/Downloads/YOUR_EXPORT.zip`. | The export zip |

Run the terminal commands from `~/Projects/tervik` while `npm run dev` is running.

**Against the hosted API.** The scripts read `TERVIK_ENDPOINT` and `TERVIK_ADMIN_TOKEN`. To keep the token out of your shell history, read it at a prompt:

```bash
read -rs "TERVIK_ADMIN_TOKEN?Admin token: " && export TERVIK_ADMIN_TOKEN TERVIK_ENDPOINT=https://api.tervik.in
```

```bash
cd ~/Projects/tervik && npm run demo:agent -- --persona general
```

## Connect your agent

The Tervik skill gives a coding agent (Claude Code, Codex, or Cursor) instructions to add Tervik to your agent's code. The **Connect agent** page walks through the same four steps. To practise on a small agent first, follow [examples/starter-agent](examples/starter-agent).

1. **Install the skill** in your agent's folder:

   ```bash
   cd ~/Projects/YOUR_AGENT && npx skills add dhanvin-ai/tervik --skill tervik -a claude-code -a codex -a cursor -y
   ```

2. **Run the prompt.** Copy the prompt from step 02 of the Connect page. It includes your project ID and endpoint. Open your agent's folder in your coding agent and paste it. Open the agent's own project, not the downloaded `tervik` skill folder; if only the skill folder is open, the skill asks for your application's path or repository URL. The skill copies a one-file client into the project, starts it once at start-up, wraps each message and tool call, and marks each change with a `tervik.instrumented` comment. Review the changes.

3. **Run your agent** with the details from step 03 of the Connect page:

   ```bash
   cd ~/Projects/YOUR_AGENT && TERVIK_PROJECT_ID=PASTE_PROJECT_ID TERVIK_ENDPOINT=https://api.tervik.in python3 agent.py
   ```

   Use `TERVIK_ENDPOINT=http://127.0.0.1:8000` for the local Tervik. If your agent starts with a different command, use that command after the two variables.

4. **Check the connection.** Send your agent a message. Step 04 of the Connect page changes from "Waiting for your agent's first event…" to **Connected**, and the conversation appears under **Conversations**.

**Monitor OpenCode itself.** To send OpenCode's own chats and tool calls to Tervik, run the second prompt in step 02 of the Connect page inside OpenCode. The skill installs a plugin ([how it works](skills/tervik/references/opencode.md)) that uses the project's secret key, then OpenCode needs a restart. It captures new messages and tool outcomes, not raw tool inputs and outputs.

The project ID can only add events to its project; it can't read anything. To use a secret key instead, open **Prefer a secret key?** on the Connect page and set `TERVIK_API_KEY` in place of `TERVIK_PROJECT_ID`. Without a coding agent, see **Prefer to add it by hand?** on the same page, or call the capture API directly ([docs/api.md](docs/api.md)).

Instrumentation runs in your agent's server process. It uses stable event IDs across retries, keeps a bounded queue in memory, and reports dropped events. Call its shutdown on exit so queued events are sent. Common secrets are filtered on a best-effort basis; add your own redaction before sending sensitive content.

## Put it online

The dashboard runs on Vercel, and the API and its Postgres database on Azure (Container Apps and Azure Database for PostgreSQL), under your own domain. `scripts/deploy_azure.sh` creates the Azure side, and every push to `main` that changes the API deploys it. [docs/deploy.md](docs/deploy.md) has every step.

## Run in containers

This runs the dashboard, the API, PostgreSQL, and a ClickHouse event mirror, with ports bound to this computer and an administrator token required.

```bash
cd ~/Projects/tervik && python3 scripts/configure_docker.py && docker compose --env-file .env.docker up --build -d
```

Open http://127.0.0.1:4173 and enter `TERVIK_ADMIN_TOKEN` from the generated `.env.docker` in **Connection settings**. The API is at http://127.0.0.1:8001. Sample data is off; set `TERVIK_DEMO_ENABLED=true` in `.env.docker` and recreate the API container to allow it. To stop, keeping the data:

```bash
cd ~/Projects/tervik && docker compose --env-file .env.docker down
```

## Check your changes

```bash
cd ~/Projects/tervik && npm run check
```

This runs the TypeScript checks, the builds, the SDK, client, API, and schema tests, and an end-to-end test from the SDK to the API with temporary storage. CI runs the same checks on every push and pull request. With the containers running, `npm run test:containers` checks PostgreSQL and the ClickHouse mirror.

## Troubleshooting

| You see | Fix |
| - | - |
| `zsh: no such file or directory: project` | A placeholder such as `<project ID>` was left in the command. Replace it with the real value, without `<` `>`. |
| `Tervik needs Python 3.11 or newer.` | Run the setup with a newer Python: `python3.14 scripts/setup_api.py`. |
| `npm run dev` fails with a `dyld` or missing-Python error | Homebrew upgraded Python under the API's environment. Recreate it: `rm -rf apps/api/.venv && python3.14 scripts/setup_api.py`. |
| "API offline" in the dashboard | Locally, start `npm run dev`. Hosted, open https://api.tervik.in/api/health; it should return `"status":"ok"`. |
| "Access denied. Sign in or add your administrator token" | Paste the token into **Administrator token**, not **Account session**, in **Connection settings**. Paste it again in each new tab. |
| Chat says Ollama is not running | `brew services start ollama`, then `ollama pull llama3.2`. On the hosted API, Chat needs `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` instead. |
| **Explore sample workspace** fails on the hosted dashboard | Set `TERVIK_DEMO_ENABLED=true` on the API: `az containerapp update --name tervik-api --resource-group tervik --set-env-vars TERVIK_DEMO_ENABLED=true`. |

## What Tervik detects

Rules flag explicit corrections, frustration, repeated requests, unsupported action claims, tool errors and timeouts, tools called with made-up values such as `[customer email]`, consequential actions (cancel, refund, delete, send, book, pay) the user never asked for, and replies that are a raw tool call instead of an answer. They are triage signals to review. Intent and policy findings come from an LLM reviewer that must cite the messages behind each finding. Without `ANTHROPIC_API_KEY`, intents use example matching and policies aren't checked. Resolving a group changes its review status; it doesn't change your agent. Billing isn't connected: plans are set by the operator.

See also [the architecture](docs/architecture.md), [the API contract](docs/api-contract.md), and [Phase 1 acceptance](docs/phase-1.md).
