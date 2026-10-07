"""Fixture tests for the Anthropic integration (no anthropic package required)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tervik.integrations import instrument_anthropic  # noqa: E402


class TextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class ToolBlock:
    def __init__(self, name, arguments):
        self.type = "tool_use"
        self.name = name
        self.input = arguments


class FakeMessages:
    def __init__(self, behavior):
        self.behavior = behavior
        self.calls = 0

    def create(self, *args, **kwargs):
        self.calls += 1
        return self.behavior(*args, **kwargs)


class FakeClient:
    def __init__(self, behavior):
        self.messages = FakeMessages(behavior)


class RecordingTervik:
    def __init__(self):
        self.events = []

    def capture(self, event):
        self.events.append(event)
        return event.get("id", "x")


class AnthropicTests(unittest.TestCase):
    def test_normal_call_with_tool_use(self):
        tervik = RecordingTervik()
        response = SimpleNamespace(
            content=[ToolBlock("lookup_policy", {"plan": "free"}),
                     TextBlock("The free plan keeps three projects.")],
            model="claude-test", usage=SimpleNamespace(input_tokens=20, output_tokens=10))
        client = FakeClient(lambda *a, **k: response)
        unpatch = instrument_anthropic(tervik, client, conversation_id="c-1", user_id="u-1")
        self.assertIs(client.messages.create(model="claude-test", messages=[]), response)
        roles = [e["role"] for e in tervik.events]
        self.assertEqual(roles, ["user", "assistant", "tool"])
        assistant = next(e for e in tervik.events if e["role"] == "assistant")
        self.assertEqual(assistant["content"], "The free plan keeps three projects.")
        self.assertEqual(assistant["tokens"], 30)
        tool = next(e for e in tervik.events if e["role"] == "tool")
        self.assertEqual(tool["name"], "lookup_policy")
        self.assertEqual(tool["parent_span_id"], assistant["span_id"])
        unpatch()
        before = len(tervik.events)
        client.messages.create(model="claude-test", messages=[])
        self.assertEqual(len(tervik.events), before)

    def test_streaming_and_errors(self):
        tervik = RecordingTervik()

        def behavior(*args, **kwargs):
            def gen():
                yield SimpleNamespace(delta=SimpleNamespace(text="Hel", content=None))
                yield SimpleNamespace(delta=SimpleNamespace(text="lo", content=None))
            return gen()

        client = FakeClient(behavior)
        instrument_anthropic(tervik, client, conversation_id="c-2")
        instrument_anthropic(tervik, client, conversation_id="c-2")
        chunks = list(client.messages.create(model="c", messages=[], stream=True))
        self.assertEqual(len(chunks), 2)
        assistant = next(e for e in tervik.events if e["role"] == "assistant")
        self.assertEqual(assistant["content"], "Hello")
        self.assertTrue(assistant["metadata"].get("streamed"))

        failure = RuntimeError("overloaded")
        bad = FakeClient(lambda *a, **k: (_ for _ in ()).throw(failure))
        instrument_anthropic(tervik, bad, conversation_id="c-3")
        with self.assertRaises(RuntimeError) as ctx:
            bad.messages.create(model="c", messages=[])
        self.assertIs(ctx.exception, failure)
        failed = next(e for e in tervik.events if e["conversation_id"] == "c-3" and e["role"] == "assistant")
        self.assertEqual(failed["status"], "error")

    def test_unsupported_client_explains(self):
        with self.assertRaises(TypeError):
            instrument_anthropic(RecordingTervik(), object(), conversation_id="c")


if __name__ == "__main__":
    unittest.main()
