# Monitor OpenCode itself

Use this recipe when the user wants the coding assistant's own OpenCode chats and tools in Tervik. The skill folder can be the current workspace; there is no customer application handler to locate for this mode. OpenCode runs the adapter through its supported plugin hooks.

## Configure and install

Obtain the user's Tervik base endpoint and project ingest credential. Reuse the selected project and existing credentials when possible. Do not invent a destination or send events to an unrelated project. If no destination is supplied, ask whether to set up a local Tervik instance or use an existing instance. Keep the key out of prompts and command arguments.

First run the included safe status helper from the skill folder:

```sh
python3 scripts/status-opencode.py
```

It reports plugin presence, whether a key is configured, endpoint health, and project ingestion counts without displaying the key. Do not use a raw file-read tool on private `tervik.json`, since that would put its secret in tool output. The helper uses a separate `TERVIK_ADMIN_TOKEN` environment variable when dashboard authorization requires it; it never sends the ingest key to dashboard routes. Reuse a working installation; a repeated setup prompt should confirm its status, not require application source or reinstall the plugin. If the chat is still following older application-only guidance, load the current skill and this reference in a new chat.

The included installer uses the `TERVIK_API_KEY` and `TERVIK_ENDPOINT` environment variables when available:

```sh
python3 scripts/install-opencode.py
```

It places `plugins/tervik.js` in OpenCode's config directory (`~/.config/opencode` or `$XDG_CONFIG_HOME/opencode`), the adapter and portable client in its `tervik/` subdirectory, and private configuration in `tervik.json` with permissions `0600`. It preserves the pseudonymous installation user ID and existing configuration on repeated installation. `--config-dir` selects another OpenCode config directory; `--endpoint` selects a base URL; `--api-key-env` selects the name of a secret environment variable, never the secret itself. If credentials are unavailable, installation can complete but ingestion remains unverified.

For a desktop app that does not inherit shell variables, configure the key and endpoint in the private `tervik.json` file. The adapter also supports `TERVIK_OPENCODE_CONFIG` to select that file at runtime. Runtime environment values override the file. Never commit this file or show its contents in logs. All helpers belong outside the plugin directory because OpenCode treats exported functions there as plugin entrypoints.

Restart OpenCode to load the plugin. Do not interrupt an active user session without their request. A separate OpenCode CLI process can verify the adapter while the desktop remains open, but the desktop still needs a restart.

## Capture and verification

- Monitor new user turns after plugin activation; do not export existing chat history. Each OpenCode session is a conversation. Message IDs provide stable turn traces; assistant message spans are parents of tool spans. Repeated completion/idle events and HTTP retries reuse stable event IDs.
- Record user and assistant text, actual model/token/cost measurements when provided, and tool name, completion/error status and timing. Do not capture reasoning, attachments, provider headers, filesystem paths, raw tool arguments or outputs. Common credentials are filtered; customize the adapter's redaction function for additional secrets or PII before export.
- Read finalized assistant messages on completion and idle events in the background. Streaming remains untouched. On idle, interrupted messages carry a partial marker and actual reported errors remain errors. Export errors do not stop OpenCode. Buffers and session tracking are bounded; this adapter does not provide durable delivery or unlimited history reconciliation.
- The `dispose` hook waits for pending reads and flushes the client; no competing process signal handlers are installed. OpenCode logs the client's safe `inspect()` counters under service `tervik`.
- Trigger a real new OpenCode interaction, including a harmless real tool call. Verify it through the project's setup and conversation APIs as described in [events.md](events.md). Test fixtures alone do not verify live ingestion. Report the dashboard link, counters, and whether the desktop restart is still pending.

Hook contract: [OpenCode plugins](https://docs.opencode.ai/docs/plugins/). The adapter uses the supported `chat.message`, `event`, and `dispose` hooks and `client.session.messages`; check those hooks against the user's installed OpenCode plugin API before claiming compatibility with a different runtime or API generation.
