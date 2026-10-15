"""Send Codex's own chats to Tervik, from Codex's command hooks.

Codex runs this once per hook event, with the event as JSON on stdin:
UserPromptSubmit records the user's message, PostToolUse each tool call, and
Stop the agent's reply. Each Codex session is one conversation and each turn
one trace. Tool arguments and outputs are not sent, only the tool's name and
whether it failed.

The hook builds the event and returns at once; a detached background process
uploads it, so Codex never waits on the network and an API that is waking up
from zero still receives it. It never writes to stdout (Codex would read that
as hook output) and never fails the hook. Installed by install-codex.py; reads
the endpoint and ingest key from TERVIK_ENDPOINT and TERVIK_API_KEY, or from
the private tervik.json beside the Codex config.
"""
# tervik.instrumented: installed as Codex hooks, not an application wrapper.
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
CODEX_HOME = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
CONFIG = Path(os.environ.get("TERVIK_CODEX_CONFIG") or CODEX_HOME / "tervik.json")
TURNS = HERE / "turns"
SECRETS = re.compile(r"\b(?:tvk_|tervik_|tvs_|sk-[A-Za-z0-9-]{8}|gh[pousr]_|github_pat_)[A-Za-z0-9_-]+")


def load_config():
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return {}


def redact(event):
    # Add rules for your own secrets or personal data here before export.
    return json.loads(SECRETS.sub("[REDACTED]", json.dumps(event)))


def failed(response):
    """Whether a tool's reported result says it failed. Unknown shapes count as success."""
    if isinstance(response, dict):
        code = response.get("exit_code", response.get("exitCode"))
        return (isinstance(code, int) and code != 0) or response.get("success") is False or \
            bool(response.get("is_error") or response.get("isError") or response.get("error"))
    return False


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def events_for(hook, config):
    """The Tervik event for one hook call, with IDs that stay the same if Codex repeats it."""
    user = str(config.get("userId") or "codex-user")[:200]
    session, turn = str(hook.get("session_id") or ""), str(hook.get("turn_id") or "")
    if not session or not turn:
        return []

    def stable(*values):
        return hashlib.sha256(json.dumps([user, *values]).encode()).hexdigest()

    base = {"conversation_id": f"codex:{session}"[:200], "user_id": user, "trace_id": stable("turn", session, turn),
            "metadata": {"source": "codex"}}
    reply_span = stable("assistant", session, turn)
    started = TURNS / stable("start", session, turn)
    event = hook.get("hook_event_name")
    if event == "UserPromptSubmit":
        TURNS.mkdir(parents=True, exist_ok=True)
        started.write_text(str(time.time()))
        # Forget turns that never stopped, so the folder stays small.
        for stale in TURNS.iterdir():
            if time.time() - stale.stat().st_mtime > 86400:
                stale.unlink(missing_ok=True)
        return [{**base, "id": stable("user", session, turn), "role": "user",
                 "content": str(hook.get("prompt") or "")[:32000], "timestamp": now()}]
    if event == "PostToolUse":
        name = str(hook.get("tool_name") or "tool")[:200]
        call = hook.get("tool_use_id") or name
        error = failed(hook.get("tool_response"))
        return [{**base, "id": stable("tool", session, turn, call), "span_id": stable("tool-span", session, turn, call),
                 "parent_span_id": reply_span, "role": "tool", "name": name, "status": "error" if error else "success",
                 "content": f"{name}: {'error' if error else 'completed'}", "timestamp": now(),
                 "metadata": {"source": "codex", "capture": "tool-metadata-only"}}]
    if event == "Stop":
        reply = {**base, "id": stable("assistant", session, turn), "span_id": reply_span, "role": "assistant",
                 "name": "codex.assistant", "content": str(hook.get("last_assistant_message") or "")[:32000],
                 "timestamp": now()}
        if hook.get("model"):
            reply["model"] = str(hook["model"])[:200]
        try:
            reply["latency_ms"] = max(0, round((time.time() - float(started.read_text())) * 1000))
            started.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
        return [reply]
    return []


def send(events, config):
    """Upload in the background process, patiently enough for an API waking from zero."""
    sys.path.insert(0, str(HERE))
    import tervik_client
    client = tervik_client.Tervik(api_key=os.environ.get("TERVIK_API_KEY") or config.get("apiKey"),
                                  endpoint=os.environ.get("TERVIK_ENDPOINT") or config.get("endpoint"),
                                  redact=redact, on_drop=lambda _: None, flush_interval=0,
                                  request_timeout=60, max_retries=2)
    for event in events:
        client.capture(event)
    client.shutdown()


if __name__ == "__main__":
    try:
        config = load_config()
        if sys.argv[1:] == ["--send"]:
            send(json.load(sys.stdin), config)
        elif os.environ.get("TERVIK_API_KEY") or config.get("apiKey"):
            events = events_for(json.load(sys.stdin), config)
            if events:
                upload = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--send"],
                                          stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                          start_new_session=True, close_fds=True)
                upload.stdin.write(json.dumps(events).encode())
                upload.stdin.close()
    except Exception:
        pass  # Monitoring must never break Codex.
    sys.exit(0)
