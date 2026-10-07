"""Replay helper tests: recorded tools serve fixtures, unknown tools fail closed."""
import asyncio
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tervik.replay import RecordedTools, UnrecordedToolError, run_case_async, run_case_sync  # noqa: E402


class ReplayTests(unittest.TestCase):
    def test_recorded_and_unrecorded(self):
        tools = RecordedTools({"lookup": "found it"})
        self.assertEqual(tools.call("lookup", {"q": "x"}), "found it")
        with self.assertRaises(UnrecordedToolError):
            tools.call("live_system")
        self.assertEqual([c["name"] for c in tools.calls], ["lookup", "live_system"])

    def test_sync_and_async_runners(self):
        case = {"input": "hi", "tools": [{"name": "lookup", "recorded_output": "ok"}]}

        def agent(prompt, tools):
            return "answer " + tools.call("lookup")

        result = run_case_sync(agent, case, None)
        self.assertEqual(result, {"response": "answer ok", "called": ["lookup"]})

        async def aagent(prompt, tools):
            return "answer " + await tools.acall("lookup")

        result = asyncio.run(run_case_async(aagent, case, None))
        self.assertEqual(result, {"response": "answer ok", "called": ["lookup"]})


if __name__ == "__main__":
    unittest.main()
