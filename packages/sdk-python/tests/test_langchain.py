"""Fixture tests for the LangChain callback handler (no langchain required)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tervik.integrations import TervikCallbackHandler  # noqa: E402


class RecordingTervik:
    def __init__(self):
        self.events = []

    def capture(self, event):
        self.events.append(event)
        return event.get("id", "x")


def generation(text):
    return SimpleNamespace(generations=[[SimpleNamespace(text=text)]])


class LangChainTests(unittest.TestCase):
    def drive(self, handler):
        handler.on_chain_start({}, {"input": "downgrade question"}, run_id="chain-1")
        handler.on_llm_start({"name": "gpt-test"}, ["downgrade question"], run_id="llm-1")
        handler.on_tool_start({"name": "lookup_policy"}, '{"plan":"free"}',
                              run_id="tool-1", parent_run_id="llm-1")
        handler.on_tool_end('{"active": 3}', run_id="tool-1")
        handler.on_llm_end(generation("3 projects stay active"), run_id="llm-1")
        handler.on_chain_end({"text": "3 projects stay active"}, run_id="chain-1")

    def test_chain_llm_tool_events_link(self):
        tervik = RecordingTervik()
        handler = TervikCallbackHandler(tervik, "c-1", user_id="u-1")
        self.drive(handler)
        by_name = {e["name"]: e for e in tervik.events if e["role"] != "user"}
        self.assertIn("gpt-test", by_name)
        self.assertIn("lookup_policy", by_name)
        tool = by_name["lookup_policy"]
        llm = by_name["gpt-test"]
        self.assertEqual(tool["trace_id"], llm["trace_id"])
        self.assertEqual(tool["parent_span_id"], llm["span_id"])
        self.assertEqual(tool["status"], "success")
        user = next(e for e in tervik.events if e["role"] == "user")
        self.assertIn("downgrade", user["content"])

    def test_errors_and_duplicate_delivery_record_once(self):
        tervik = RecordingTervik()
        handler = TervikCallbackHandler(tervik, "c-2")
        handler.on_llm_start({}, ["q"], run_id="llm-9")
        failure = RuntimeError("tool exploded")
        handler.on_tool_start({"name": "broken"}, "{}", run_id="tool-9", parent_run_id="llm-9")
        handler.on_tool_error(failure, run_id="tool-9")
        # Duplicate redelivery of the same run must not create a second stream.
        handler.on_tool_error(failure, run_id="tool-9")
        handler.on_llm_error(failure, run_id="llm-9")
        handler.on_llm_error(failure, run_id="llm-9")
        errors = [e for e in tervik.events if e.get("status") == "error"]
        self.assertEqual(len(errors), 2)
        self.assertEqual(handler.run_count, 0)


if __name__ == "__main__":
    unittest.main()
