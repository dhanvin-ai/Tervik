"""Fixture tests for the OpenAI integration (no openai package required)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tervik import Tervik  # noqa: E402
from tervik.integrations import instrument_openai  # noqa: E402


class FakeDelta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeChoice:
    def __init__(self, message=None, delta=None):
        self.message = message
        self.delta = delta


class FakeResponse:
    def __init__(self, text=None, chunks=None, model="gpt-test", tokens=12, tool_calls=None):
        self.model = model
        self.usage = SimpleNamespace(total_tokens=tokens)
        if chunks is not None:
            self._chunks = chunks
        else:
            self.choices = [FakeChoice(message=SimpleNamespace(content=text, tool_calls=tool_calls))]


class FakeCompletions:
    def __init__(self, behavior):
        self.behavior = behavior
        self.calls = 0

    def create(self, *args, **kwargs):
        self.calls += 1
        return self.behavior(*args, **kwargs)


class FakeChat:
    def __init__(self, behavior):
        self.completions = FakeCompletions(behavior)


class FakeClient:
    def __init__(self, behavior):
        self.chat = FakeChat(behavior)


class RecordingTervik:
    def __init__(self):
        self.events = []

    def capture(self, event):
        self.events.append(event)
        return event.get("id", "x")


class OpenAITests(unittest.TestCase):
    def test_normal_call_records_turn_and_tool_calls(self):
        tervik = RecordingTervik()
        client = FakeClient(lambda *a, **k: FakeResponse(
            text="downgrade keeps 3 projects",
            tool_calls=[{"name": "lookup_policy", "arguments": '{"plan":"free"}'}]))
        unpatch = instrument_openai(tervik, client, conversation_id="c-1", user_id="u-1")
        response = client.chat.completions.create(
            model="gpt-test", messages=[{"role": "user", "content": "what happens on downgrade?"}])
        self.assertEqual(response.choices[0].message.content, "downgrade keeps 3 projects")
        roles = [e["role"] for e in tervik.events]
        self.assertEqual(roles, ["user", "assistant", "tool"])
        assistant = next(e for e in tervik.events if e["role"] == "assistant")
        self.assertEqual(assistant["content"], "downgrade keeps 3 projects")
        self.assertEqual(assistant["tokens"], 12)
        tool = next(e for e in tervik.events if e["role"] == "tool")
        self.assertEqual(tool["name"], "lookup_policy")
        self.assertEqual(tool["parent_span_id"], assistant["span_id"])
        unpatch()
        before = len(tervik.events)
        client.chat.completions.create(model="gpt-test", messages=[])
        self.assertEqual(len(tervik.events), before)

    def test_streaming_errors_and_reinstrumentation(self):
        tervik = RecordingTervik()

        def behavior(*args, **kwargs):
            def gen():
                yield FakeResponse(chunks=True)
                gen_chunks = [FakeChoice(delta=FakeDelta(content="Hel")),
                              FakeChoice(delta=FakeDelta(content="lo"))]
                for chunk in gen_chunks:
                    yield SimpleNamespace(choices=[chunk])
            return gen()

        client = FakeClient(behavior)
        first = instrument_openai(tervik, client, conversation_id="c-2")
        second = instrument_openai(tervik, client, conversation_id="c-2")
        self.assertIsNotNone(first)
        chunks = list(client.chat.completions.create(model="gpt-test", messages=[], stream=True))
        self.assertEqual(len(chunks), 3)
        assistant = next(e for e in tervik.events if e["role"] == "assistant")
        self.assertEqual(assistant["content"], "Hello")
        self.assertTrue(assistant["metadata"].get("streamed"))

        failure = RuntimeError("provider down")
        bad = FakeClient(lambda *a, **k: (_ for _ in ()).throw(failure))
        instrument_openai(tervik, bad, conversation_id="c-3")
        with self.assertRaises(RuntimeError) as ctx:
            bad.chat.completions.create(model="gpt-test", messages=[])
        self.assertIs(ctx.exception, failure)
        failed = next(e for e in tervik.events if e["conversation_id"] == "c-3" and e["role"] == "assistant")
        self.assertEqual(failed["status"], "error")

    def test_unsupported_client_explains(self):
        with self.assertRaises(TypeError):
            instrument_openai(RecordingTervik(), object(), conversation_id="c")


if __name__ == "__main__":
    unittest.main()
