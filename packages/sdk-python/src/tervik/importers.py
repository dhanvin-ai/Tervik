"""Import conversations from apps you cannot instrument: OpenAI Codex session
files and ChatGPT data exports.

Each source conversation becomes one Tervik session. Each user request
becomes one turn pair (the request and the final reply), and the commands,
file edits, MCP calls, web searches, and tools used along the way become tool
calls nested under that turn. Event ids are derived from the source ids, so
importing the same data twice adds nothing.
"""

import glob
import json
import os
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

MAX_TEXT = 8000
NAMESPACE = uuid.UUID("6f9b3c1e-2d4a-4b8e-9c7d-1a2b3c4d5e6f")


@dataclass
class Conversation:
    session: dict
    events: list = field(default_factory=list)


def stable_id(*parts):
    return str(uuid.uuid5(NAMESPACE, ":".join(str(p) for p in parts)))


def clip(value, limit=MAX_TEXT):
    text = value if isinstance(value, str) else ("" if value is None else json.dumps(value, ensure_ascii=False, default=str))
    return text if len(text) <= limit else text[:limit] + " …[truncated]"


def to_ms(value):
    """Seconds, milliseconds, or an ISO timestamp -> epoch milliseconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value * 1000) if value < 1e11 else int(value)
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def duration_ms(value):
    if isinstance(value, dict):
        return round(value.get("secs", 0) * 1000 + value.get("nanos", 0) / 1e6, 3)
    return value if isinstance(value, (int, float)) else None


def tool_event(conversation_id, source, item_id, parent_id, name, args, result, success, started, latency, metadata=None):
    event = {"event_id": stable_id(source, conversation_id, item_id), "session_id": conversation_id,
             "primitive_name": (name or "tool")[:200], "args": clip(args), "result": clip(result),
             "success": bool(success), "parent_id": parent_id, "metadata": metadata or {}}
    if started:
        event["timestamp"] = started
    if latency is not None and latency >= 0:
        event["latency"] = latency
    return event


# ---- OpenAI Codex ----

def codex_files(home=None):
    root = Path(home or os.getenv("CODEX_HOME") or Path.home() / ".codex") / "sessions"
    return sorted(glob.glob(str(root / "**" / "*.jsonl"), recursive=True))


def _codex_text(parts):
    texts = []
    for part in parts or []:
        if isinstance(part, dict):
            if part.get("text"):
                texts.append(part["text"])
            elif part.get("path") or part.get("type") in ("image", "input_image", "localImage"):
                texts.append("[image]")
    return "\n".join(texts).strip()


def _codex_tool(item, cwd):
    """(name, args, result, success, metadata) for a completed Codex item, or None."""
    kind = item.get("type")
    status = item.get("status")
    if kind == "CommandExecution":
        command = item.get("command") or []
        if isinstance(command, list) and len(command) >= 3 and command[1] in ("-lc", "-c"):
            shown = command[2]
        else:
            shown = " ".join(command) if isinstance(command, list) else str(command)
        code = item.get("exit_code")
        return ("shell", shown, item.get("aggregated_output") or item.get("stdout") or "",
                status == "completed" and code in (0, None), {"exit_code": "" if code is None else str(code)})
    if kind == "McpToolCall":
        result = item.get("result") or {}
        texts = [c.get("text", "") if c.get("type") == "text" else f"[{c.get('type', 'content')}]"
                 for c in (result.get("content") or []) if isinstance(c, dict)]
        return (f'{item.get("server") or "mcp"}.{item.get("tool") or "tool"}', item.get("arguments") or {},
                "\n".join(texts), status == "completed" and not result.get("isError"), {})
    if kind == "FileChange":
        paths = sorted(os.path.relpath(p, cwd) if cwd and p.startswith(cwd) else p for p in (item.get("changes") or {}))
        return ("apply_patch", paths, f"{len(paths)} file(s) changed", status == "completed", {})
    if kind == "WebSearch":
        action = item.get("action") or {}
        query = item.get("query") or action.get("query") or action.get("queries") or action.get("url") or ""
        return ("web.search", query, "", True, {})
    if kind == "Extension":
        failure = item.get("failure")
        return (item.get("kind") or "extension", item.get("query") or item.get("revisedPrompt") or "",
                failure or "", not failure and status in (None, "completed"), {})
    if kind == "CollabAgentToolCall":
        return (f'agents.{item.get("tool") or "call"}', {"agents": len(item.get("receiver_thread_ids") or [])},
                "", status in (None, "completed"), {})
    return None


def parse_codex(path, user_id, since_ms=None):
    """One Codex session file -> Conversation, with only finished turns."""
    meta, turns = None, {}

    def turn(turn_id):
        return turns.setdefault(turn_id, {"started": None, "inputs": [], "finals": [], "tools": [], "model": None,
                                          "tokens": None, "done": False, "aborted": False, "error": None,
                                          "duration": None, "last": None, "completed": None})

    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            kind, payload = record.get("type"), record.get("payload") or {}
            if kind == "session_meta" and meta is None:
                meta = payload
            elif kind == "turn_context" and payload.get("turn_id"):
                turn(payload["turn_id"])["model"] = payload.get("model")
            elif kind == "token_usage_record" and payload.get("turn_id"):
                usage = payload.get("turn_token_usage") or payload.get("usage") or {}
                if isinstance(usage, dict) and usage.get("total_tokens") is not None:
                    turn(payload["turn_id"])["tokens"] = usage["total_tokens"]
            elif kind == "event_msg" and payload.get("turn_id"):
                current, event = turn(payload["turn_id"]), payload.get("type")
                if event == "task_started":
                    current["started"] = to_ms(payload.get("started_at"))
                elif event == "item_completed":
                    item = payload.get("item") or {}
                    if item.get("type") == "UserMessage":
                        text = _codex_text(item.get("content"))
                        if text:
                            current["inputs"].append(text)
                    elif item.get("type") == "AgentMessage" and item.get("phase") != "commentary":
                        text = _codex_text(item.get("content"))
                        if text:
                            current["finals"].append(text)
                    else:
                        current["tools"].append((item, payload.get("started_at_ms"), payload.get("completed_at_ms")))
                elif event in ("task_complete", "turn_aborted"):
                    current["done"] = True
                    current["aborted"] = event == "turn_aborted"
                    error = payload.get("error")
                    current["error"] = (error.get("message") if isinstance(error, dict) else error) or None
                    current["duration"] = payload.get("duration_ms")
                    current["last"] = payload.get("last_agent_message")
                    current["completed"] = to_ms(payload.get("completed_at"))
    if meta is None:
        return None
    conversation_id = meta.get("id") or meta.get("session_id") or Path(path).stem
    source = meta.get("source")
    subagent = isinstance(source, dict) and "subagent" in source
    if subagent:
        role = source["subagent"]
        agent = "codex-auto-review" if isinstance(role, dict) and role.get("other") == "guardian" else \
            f'codex-{meta.get("agent_nickname") or "subagent"}'.lower().replace(" ", "-")
    else:
        agent = "codex"
    cwd = meta.get("cwd") or ""
    session = {"session_id": conversation_id, "user_data": {"user_id": user_id, "app": "codex"},
               "metadata": {"source": "codex", "app": str(meta.get("originator") or "codex"),
                            "project": os.path.basename(cwd.rstrip("/")) or "unknown",
                            "subagent": "yes" if subagent else "no",
                            "client_version": str(meta.get("cli_version") or "")},
               "timestamp": to_ms(meta.get("timestamp")), "client_config": "tervik-import/codex"}
    conversation = Conversation(session=session)
    for turn_id, current in turns.items():
        if not current["done"]:
            continue
        started = current["started"] or min((s for _, s, _ in current["tools"] if s), default=None) or \
            ((current["completed"] - current["duration"]) if current["completed"] and current["duration"] else current["completed"])
        if since_ms and started and started < since_ms:
            continue
        output = "\n\n".join(current["finals"]) or current["last"] or \
            ("Interrupted by the user." if current["aborted"] else current["error"] or "")
        metadata = {"turn_id": turn_id}
        if current["model"]:
            metadata["model"] = current["model"]
        if current["tokens"] is not None:
            metadata["tokens"] = str(current["tokens"])
        if current["aborted"]:
            metadata["outcome"] = "interrupted"
        turn_event = {"event_id": stable_id("codex", conversation_id, turn_id), "session_id": conversation_id,
                      "primitive_name": agent, "args": clip("\n\n".join(current["inputs"])), "result": clip(output),
                      "success": not current["aborted"] and not current["error"], "metadata": metadata}
        if started:
            turn_event["timestamp"] = started
        if current["duration"] is not None:
            turn_event["latency"] = current["duration"]
        conversation.events.append(turn_event)
        for item, item_started, item_completed in current["tools"]:
            mapped = _codex_tool(item, cwd)
            if mapped is None or not item.get("id"):
                continue
            name, args, result, success, extra = mapped
            latency = duration_ms(item.get("duration"))
            if latency is None and item_started and item_completed:
                latency = item_completed - item_started
            conversation.events.append(tool_event(conversation_id, "codex", item["id"], turn_event["event_id"], name,
                                                  args, result, success, item_started or started, latency, extra))
    return conversation


# ---- ChatGPT data export ----

def load_chatgpt(path):
    """Conversations from an export .zip, its conversations.json, or the unzipped folder."""
    path = Path(path).expanduser()
    if path.is_dir():
        files = sorted(path.glob("conversations*.json"))
        return [c for f in files for c in json.loads(f.read_text(encoding="utf-8"))]
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = sorted(n for n in archive.namelist() if os.path.basename(n).startswith("conversations") and n.endswith(".json"))
            if not names:
                raise ValueError("No conversations.json in this export")
            return [c for n in names for c in json.loads(archive.read(n).decode("utf-8"))]
    return json.loads(path.read_text(encoding="utf-8"))


def _chatgpt_text(content):
    content = content or {}
    kind = content.get("content_type")
    if "parts" in content:
        parts = []
        for part in content.get("parts") or []:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(part.get("text") or ("[image]" if "image" in str(part.get("content_type", "")) or
                                                  part.get("asset_pointer") else "[attachment]"))
        return "\n".join(p for p in parts if p).strip()
    if kind == "tether_browsing_display":
        return content.get("result") or content.get("summary") or ""
    if kind == "tether_quote":
        return "\n".join(x for x in (content.get("title"), content.get("url"), content.get("text")) if x)
    return content.get("text") or ""


HIDDEN_TYPES = {"user_editable_context", "model_editable_context", "thoughts", "reasoning_recap"}


def _chatgpt_branch(conversation):
    """The messages on the branch the user last saw, oldest first."""
    mapping, node, branch = conversation.get("mapping") or {}, conversation.get("current_node"), []
    seen = set()
    while node and node in mapping and node not in seen:
        seen.add(node)
        message = mapping[node].get("message")
        if message:
            branch.append(message)
        node = mapping[node].get("parent")
    return list(reversed(branch))


def _tool_failed(message, text):
    content = message.get("content") or {}
    result = ((message.get("metadata") or {}).get("aggregate_result") or {})
    status = str(result.get("status", ""))
    return content.get("content_type") == "system_error" or "fail" in status or "exception" in status \
        or text.lstrip().startswith(("Error", "Traceback"))


def parse_chatgpt(conversation, user_id, since_ms=None):
    conversation_id = conversation.get("conversation_id") or conversation.get("id")
    if not conversation_id:
        return None
    updated = to_ms(conversation.get("update_time")) or to_ms(conversation.get("create_time"))
    if since_ms and updated and updated < since_ms:
        return None
    session = {"session_id": conversation_id, "user_data": {"user_id": user_id, "app": "chatgpt"},
               "metadata": {"source": "chatgpt", "title": clip(conversation.get("title") or "Untitled", 200)},
               "timestamp": to_ms(conversation.get("create_time")), "client_config": "tervik-import/chatgpt"}
    if conversation.get("gizmo_id"):
        session["metadata"]["gpt"] = str(conversation["gizmo_id"])
    result, current = Conversation(session=session), None
    default_model = conversation.get("default_model_slug")

    def finish(turn):
        if turn is None:
            return
        last = turn["last"] or turn["started"]
        metadata = {"model": turn["model"] or default_model} if (turn["model"] or default_model) else {}
        event = {"event_id": stable_id("chatgpt", conversation_id, turn["id"]), "session_id": conversation_id,
                 "primitive_name": "chatgpt", "args": clip(turn["input"]),
                 "result": clip("\n\n".join(turn["outputs"]) or "(no reply)"),
                 "success": bool(turn["outputs"]) and not turn["error"], "metadata": metadata}
        if turn["started"]:
            event["timestamp"] = turn["started"]
            if last and last >= turn["started"]:
                event["latency"] = last - turn["started"]
        if since_ms and turn["started"] and turn["started"] < since_ms:
            return
        result.events.append(event)
        for tool in turn["tools"]:
            result.events.append(tool_event(conversation_id, "chatgpt", tool["id"], event["event_id"], tool["name"],
                                            tool["args"], tool["result"], tool["success"], tool["started"],
                                            (tool["ended"] - tool["started"]) if tool["ended"] and tool["started"] else None))

    for message in _chatgpt_branch(conversation):
        author = message.get("author") or {}
        role, content = author.get("role"), message.get("content") or {}
        metadata = message.get("metadata") or {}
        if role == "system" or metadata.get("is_visually_hidden_from_conversation") or \
                content.get("content_type") in HIDDEN_TYPES:
            continue
        stamp, text = to_ms(message.get("create_time")), _chatgpt_text(content)
        if role == "user":
            finish(current)
            current = {"id": message.get("id"), "input": text or "[attachment]", "started": stamp, "last": None,
                       "outputs": [], "tools": [], "model": None, "error": False}
            continue
        if current is None:
            continue
        if stamp:
            current["last"] = max(current["last"] or stamp, stamp)
        if role == "assistant":
            current["model"] = metadata.get("model_slug") or current["model"]
            recipient = message.get("recipient") or "all"
            if recipient != "all":
                current["tools"].append({"id": message.get("id"), "name": recipient, "args": text, "result": "",
                                         "success": True, "started": stamp, "ended": None, "open": True})
            elif text:
                current["outputs"].append(text)
            if content.get("content_type") == "system_error":
                current["error"] = True
        elif role == "tool":
            name = author.get("name") or "tool"
            pending = next((t for t in reversed(current["tools"]) if t["open"] and t["name"] == name), None) or \
                next((t for t in reversed(current["tools"]) if t["open"]), None)
            if pending is None:
                pending = {"id": message.get("id"), "name": name, "args": "", "result": "", "success": True,
                           "started": stamp, "ended": None, "open": True}
                current["tools"].append(pending)
            pending.update(result=text, ended=stamp, open=False, success=not _tool_failed(message, text))
    finish(current)
    return result


# ---- sending ----

class Uploader:
    """Posts sessions and events to the capture API with bounded retries."""

    def __init__(self, api, project_id, timeout=30.0, retries=3):
        self.api, self.project_id, self.timeout, self.retries = api.rstrip("/"), project_id, timeout, retries
        self.sent, self.rejected = 0, 0

    def post(self, path, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "x-org-id": self.project_id,
                   "X-Tervik-Client": "tervik-import"}
        for attempt in range(self.retries + 1):
            request = urllib.request.Request(self.api + path, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    response.read()
                self.sent += 1
                return True
            except urllib.error.HTTPError as error:
                status = error.code
                error.close()
                if status in (401, 403, 404):
                    raise SystemExit(f"Tervik rejected project {self.project_id} (HTTP {status}).")
                if status == 429:
                    raise SystemExit("The project's event allowance is used up (HTTP 429).")
                if status < 500:
                    self.rejected += 1
                    return False
            except urllib.error.URLError:
                if attempt == self.retries:
                    raise SystemExit(f"Cannot reach Tervik at {self.api}. Start it with: npm run dev")
            time.sleep(min(4.0, 0.5 * 2 ** attempt))
        self.rejected += 1
        return False

    def send(self, conversation, skip=frozenset()):
        """Send the session and any events not in `skip`. Returns the ids sent."""
        fresh = [e for e in conversation.events if e["event_id"] not in skip]
        if not fresh:
            return []
        session = {k: v for k, v in conversation.session.items() if v is not None}
        self.post("/api/v1/capture-session", session)
        done = []
        for event in fresh:
            body = {k: v for k, v in event.items() if v is not None}
            if self.post("/api/v1/capture-event", body):
                done.append(event["event_id"])
        return done
