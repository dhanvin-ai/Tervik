"""Codex session files and ChatGPT exports map onto turns and nested tool calls."""
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tervik.importers import load_chatgpt, parse_chatgpt, parse_codex  # noqa: E402

T0 = 1_790_000_000  # seconds


def codex_file(folder, records):
    path = Path(folder) / "rollout-test.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n{not json\n")
    return path


def event(turn, kind, **payload):
    return {"type": "event_msg", "timestamp": "2026-10-01T00:00:00Z", "payload": {"type": kind, "turn_id": turn, **payload}}


def item(turn, body, start=None, end=None):
    return event(turn, "item_completed", item=body, started_at_ms=start, completed_at_ms=end, thread_id="th-1")


CODEX = [
    {"type": "session_meta", "payload": {"id": "th-1", "cwd": "/Users/me/shop", "originator": "Codex Desktop",
                                         "cli_version": "1.2.3", "source": "vscode", "timestamp": "2026-10-01T00:00:00Z"}},
    {"type": "turn_context", "payload": {"turn_id": "t1", "model": "gpt-6.1"}},
    event("t1", "task_started", started_at=T0),
    item("t1", {"type": "UserMessage", "id": "u1", "content": [{"type": "text", "text": "Fix the failing test"}, {"type": "localImage", "path": "/tmp/x.png"}]}),
    item("t1", {"type": "Reasoning", "id": "r1"}),
    item("t1", {"type": "CommandExecution", "id": "c1", "command": ["/bin/zsh", "-lc", "npm test"], "status": "failed",
                "exit_code": 1, "aggregated_output": "1 failing", "duration": {"secs": 2, "nanos": 500_000_000}},
         T0 * 1000 + 100, T0 * 1000 + 2600),
    item("t1", {"type": "FileChange", "id": "f1", "status": "completed", "changes": {"/Users/me/shop/src/app.ts": {}}}),
    item("t1", {"type": "McpToolCall", "id": "m1", "server": "github", "tool": "create_pr", "status": "completed",
                "arguments": {"title": "Fix"}, "result": {"content": [{"type": "text", "text": "PR #4"}], "isError": False},
                "duration": {"secs": 1, "nanos": 0}}),
    item("t1", {"type": "AgentMessage", "id": "a0", "phase": "commentary", "content": [{"type": "text", "text": "Looking..."}]}),
    item("t1", {"type": "AgentMessage", "id": "a1", "phase": "final_answer", "content": [{"type": "text", "text": "Fixed and opened PR #4."}]}),
    {"type": "token_usage_record", "payload": {"turn_id": "t1", "turn_token_usage": {"total_tokens": 5120}}},
    event("t1", "task_complete", duration_ms=9000, completed_at=T0 + 9, error=None, last_agent_message="Fixed and opened PR #4."),
    event("t2", "task_started", started_at=T0 + 60),
    item("t2", {"type": "UserMessage", "id": "u2", "content": [{"type": "text", "text": "Now deploy it"}]}),
    event("t2", "turn_aborted", reason="interrupted", duration_ms=4000),
    event("t3", "task_started", started_at=T0 + 120),
    item("t3", {"type": "UserMessage", "id": "u3", "content": [{"type": "text", "text": "Still running"}]}),
]


class CodexTests(unittest.TestCase):
    def test_turns_tools_and_outcomes(self):
        with tempfile.TemporaryDirectory() as folder:
            conversation = parse_codex(codex_file(folder, CODEX), "me")
        session = conversation.session
        self.assertEqual(session["session_id"], "th-1")
        self.assertEqual(session["metadata"]["project"], "shop")
        self.assertEqual(session["metadata"]["subagent"], "no")
        turns = [e for e in conversation.events if "parent_id" not in e]
        self.assertEqual(len(turns), 2)  # the unfinished third turn waits
        first, aborted = turns
        self.assertEqual(first["args"], "Fix the failing test\n[image]")
        self.assertEqual(first["result"], "Fixed and opened PR #4.")
        self.assertEqual(first["timestamp"], T0 * 1000)
        self.assertEqual(first["latency"], 9000)
        self.assertEqual(first["metadata"], {"turn_id": "t1", "model": "gpt-6.1", "tokens": "5120"})
        self.assertTrue(first["success"])
        self.assertFalse(aborted["success"])
        self.assertEqual(aborted["result"], "Interrupted by the user.")
        tools = {e["primitive_name"]: e for e in conversation.events if e.get("parent_id")}
        self.assertEqual(set(tools), {"shell", "apply_patch", "github.create_pr"})
        self.assertEqual(tools["shell"]["args"], "npm test")
        self.assertFalse(tools["shell"]["success"])
        self.assertEqual(tools["shell"]["latency"], 2500)
        self.assertEqual(tools["shell"]["metadata"], {"exit_code": "1"})
        self.assertEqual(tools["apply_patch"]["args"], '["src/app.ts"]')
        self.assertEqual(tools["github.create_pr"]["result"], "PR #4")
        self.assertTrue(all(t["parent_id"] == first["event_id"] for t in tools.values()))
        with tempfile.TemporaryDirectory() as folder:
            again = parse_codex(codex_file(folder, CODEX), "me")
        self.assertEqual([e["event_id"] for e in again.events], [e["event_id"] for e in conversation.events])

    def test_since_and_subagents(self):
        records = [{**CODEX[0], "payload": {**CODEX[0]["payload"], "source": {"subagent": {"other": "guardian"}}}}] + CODEX[1:]
        with tempfile.TemporaryDirectory() as folder:
            conversation = parse_codex(codex_file(folder, records), "me", since_ms=(T0 + 30) * 1000)
            self.assertIsNone(parse_codex(codex_file(folder, CODEX[1:]), "me"))
        self.assertEqual(conversation.session["metadata"]["subagent"], "yes")
        self.assertEqual([e["primitive_name"] for e in conversation.events], ["codex-auto-review"])


def node(id, parent, role, text=None, *, name=None, recipient="all", content=None, t=0.0, metadata=None):
    message = {"id": id, "author": {"role": role, "name": name}, "create_time": T0 + t, "recipient": recipient,
               "content": content or {"content_type": "text", "parts": [text]}, "metadata": metadata or {}}
    return id, {"id": id, "parent": parent, "message": message}


CHATGPT = {
    "id": "conv-1", "title": "Trip planning", "create_time": T0, "update_time": T0 + 100,
    "default_model_slug": "gpt-6", "current_node": "a3",
    "mapping": dict([
        ("root", {"id": "root", "parent": None, "message": None}),
        node("s0", "root", "system", "", metadata={"is_visually_hidden_from_conversation": True}),
        node("u1", "s0", "user", "Find flights to Goa", t=1),
        node("c1", "u1", "assistant", recipient="web.run", content={"content_type": "code", "text": "search flights goa"}, t=2),
        node("r1", "c1", "tool", name="web.run", content={"content_type": "tether_browsing_display", "result": "3 flights found"}, t=4),
        node("x1", "r1", "assistant", content={"content_type": "thoughts", "thoughts": []}, t=4.5),
        node("a1", "x1", "assistant", "Here are 3 flights.", t=5, metadata={"model_slug": "gpt-6-thinking"}),
        node("u2", "a1", "user", "Plot prices", t=10),
        node("c2", "u2", "assistant", recipient="python", content={"content_type": "code", "text": "plot(prices)"}, t=11),
        node("r2", "c2", "tool", name="python", content={"content_type": "execution_output", "text": "Traceback: NameError"}, t=12,
             metadata={"aggregate_result": {"status": "failed_with_in_kernel_exception"}}),
        node("a2", "r2", "assistant", "Sorry, plotting failed.", t=13),
        node("u3", "a1", "user", "An abandoned branch", t=20),
        node("a3", "a2", "assistant", "Anything else?", t=14),
    ]),
}


class ChatGPTTests(unittest.TestCase):
    def test_branch_turns_and_tools(self):
        conversation = parse_chatgpt(CHATGPT, "me")
        self.assertEqual(conversation.session["metadata"], {"source": "chatgpt", "title": "Trip planning"})
        turns = [e for e in conversation.events if "parent_id" not in e]
        self.assertEqual([t["args"] for t in turns], ["Find flights to Goa", "Plot prices"])
        self.assertEqual(turns[0]["result"], "Here are 3 flights.")
        self.assertEqual(turns[0]["latency"], 4000)
        self.assertEqual(turns[0]["metadata"], {"model": "gpt-6-thinking"})
        self.assertEqual(turns[1]["result"], "Sorry, plotting failed.\n\nAnything else?")
        self.assertEqual(turns[1]["metadata"], {"model": "gpt-6"})
        tools = [e for e in conversation.events if e.get("parent_id")]
        self.assertEqual([(t["primitive_name"], t["args"], t["result"], t["success"]) for t in tools],
                         [("web.run", "search flights goa", "3 flights found", True),
                          ("python", "plot(prices)", "Traceback: NameError", False)])
        self.assertEqual(tools[0]["latency"], 2000)
        self.assertEqual(tools[1]["parent_id"], turns[1]["event_id"])

    def test_loading_exports_and_filtering(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "export.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("conversations.json", json.dumps([CHATGPT]))
            self.assertEqual(len(load_chatgpt(archive)), 1)
            (Path(folder) / "conversations.json").write_text(json.dumps([CHATGPT]))
            self.assertEqual(len(load_chatgpt(folder)), 1)
        self.assertIsNone(parse_chatgpt(CHATGPT, "me", since_ms=(T0 + 1000) * 1000))
        self.assertIsNone(parse_chatgpt({"mapping": {}}, "me"))


if __name__ == "__main__":
    unittest.main()
