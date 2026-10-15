# Monitor Codex itself

Use this recipe when the user wants Codex's own chats and tool calls in Tervik. The skill folder can be the current workspace; there is no application handler to find. Codex runs the adapter through its supported command hooks: `UserPromptSubmit` (the user's message), `PostToolUse` (each tool call), and `Stop` (the reply).

## Configure and install

Get the user's Tervik endpoint and the project's **secret ingest key**: the dashboard's **Connect your agent** page, step 03, *Prefer a secret key?* The public project ID doesn't work here. Don't invent a destination or send events to an unrelated project. Keep the key out of prompts and command arguments: the user sets it in the environment of the shell that runs the installer.

First check for an existing installation with the safe status helper, which never shows the key:

```sh
python3 scripts/status-codex.py
```

Reuse a working installation. To install or update:

```sh
python3 scripts/install-codex.py
```

It reads `TERVIK_API_KEY` and `TERVIK_ENDPOINT` and does three things:
- Copies `codex-hook.py` and the portable client into `~/.codex/tervik/`, or `$CODEX_HOME/tervik/` if `CODEX_HOME` is set.
- Stores the key, endpoint, and a pseudonymous installation user ID in `~/.codex/tervik.json`, with permissions `0600`.
- Adds the three hooks to `~/.codex/hooks.json`, beside any hooks already there. Running it again replaces only Tervik's entries.

`--codex-home` selects another Codex home, `--endpoint` a base URL, and `--api-key-env` the name of the variable holding the key (never the key itself). Never show `tervik.json` or commit it.

Then the user restarts Codex. Codex runs a new or changed hook only after it's reviewed and trusted. When Codex asks, the user trusts the three Tervik hooks; in the CLI, `/hooks` lists them. Don't bypass hook trust for them.

## Capture and verification

- Only new turns are sent, not existing history. Each Codex session is one conversation (`codex:<session id>`), and each turn one trace, with tool calls nested under the reply. Event IDs are stable, so a repeated hook call is recorded once.
- Sent: the user's prompt, the final reply, the model name, the turn's duration, and each tool's name and whether it failed. Not sent: tool arguments, tool output, file contents, or paths. Common credential formats are redacted; add rules to `redact()` in `codex-hook.py` for other secrets or personal data.
- The hook returns to Codex at once. A detached background process uploads the event, patiently enough for an API that is waking up from zero. It never writes to stdout and never fails the hook, so Tervik being down doesn't affect Codex.
- To verify, send one real message in Codex that runs a harmless command, such as listing files. Then check that it arrived: the project's **Connect your agent** page turns to **Connected**, or use the setup and conversation APIs in [events.md](events.md). Report the dashboard link, and whether Codex still needs a restart or the hooks still need trusting.

Hook contract: [Codex hooks](https://developers.openai.com/codex/hooks). Check the user's Codex version supports `UserPromptSubmit`, `PostToolUse`, and `Stop` command hooks before claiming compatibility.
