"""Behavior tests for the Python client shipped in the downloadable skill."""
import asyncio
import importlib.util
import json
import sys
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.dont_write_bytecode = True

client_path = Path(__file__).resolve().parents[3] / "skills" / "tervik" / "scripts" / "tervik_client.py"
spec = importlib.util.spec_from_file_location("tervik_client", client_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Tervik = module.Tervik


@contextmanager
def mock_api(handler):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({"body": body, "path": self.path, "authorization": self.headers.get("Authorization")})
            status, payload = handler(body, len(requests))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port), requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def new_client(endpoint, **kwargs):
    return Tervik(api_key="project-key", endpoint=endpoint, flush_interval=0, retry_base=0, on_drop=lambda _notice: None, **kwargs)


class ClientTests(unittest.TestCase):
    def test_invalid_fields_cannot_poison_a_valid_batch(self):
        with mock_api(lambda body, _attempt: (200, {"accepted": len(body["events"]), "duplicates": 0})) as (endpoint, requests):
            client = new_client(endpoint)
            valid = {"conversation_id": "valid-source", "role": "user", "content": "Actual request", "tokens": 3}
            invalid = [
                {"tokens": 3.5}, {"tokens": 3.0}, {"tokens": True}, {"name": "x" * 201},
                {"id": "x" * 201}, {"conversation_id": "x" * 201},
                {"metadata": {"value": float("inf")}}, {"project_id": "not-authorization"},
                {"timestamp": "2026-10-06T12:00:00"},
                {"timestamp": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()},
            ]
            for fields in invalid:
                self.assertIsNone(client.capture({**valid, **fields}))
            self.assertIsNotNone(client.capture(valid))
            self.assertEqual(client.flush()["accepted"], 1)
            self.assertEqual(len(requests[0]["body"]["events"]), 1)
            self.assertEqual(client.inspect()["drops"]["invalid_event"], len(invalid))
            client.shutdown()

    def test_batch_contract_and_redaction(self):
        with mock_api(lambda body, _attempt: (200, {"accepted": len(body["events"]), "duplicates": 0})) as (endpoint, requests):
            client = new_client(endpoint)
            event_id = client.capture({"conversation_id": "real", "role": "user", "content": "Bearer abc123", "metadata": {"password": "hidden"}})
            for index in range(100):
                client.capture({"conversation_id": "real", "role": "assistant", "content": str(index)})
            self.assertEqual(client.flush()["accepted"], 101)
            self.assertEqual([len(item["body"]["events"]) for item in requests], [100, 1])
            first = requests[0]
            self.assertEqual(first["path"], "/v1/events")
            self.assertEqual(first["authorization"], "Bearer project-key")
            self.assertEqual(first["body"]["events"][0]["id"], event_id)
            self.assertEqual(first["body"]["events"][0]["content"], "Bearer [REDACTED]")
            self.assertEqual(first["body"]["events"][0]["metadata"]["password"], "[REDACTED]")
            client.shutdown()

    def test_retries_preserve_ids(self):
        with mock_api(lambda body, attempt: (503, {}) if attempt < 3 else (200, {"accepted": 0, "duplicates": len(body["events"])})) as (endpoint, requests):
            client = new_client(endpoint)
            client.capture({"conversation_id": "retry", "role": "user", "content": "actual message"})
            self.assertEqual(client.flush()["duplicates"], 1)
            self.assertEqual(len(requests), 3)
            self.assertEqual(len({item["body"]["events"][0]["id"] for item in requests}), 1)
            client.shutdown()

    def test_auth_disables_and_drops_pending(self):
        with mock_api(lambda _body, _attempt: (401, {})) as (endpoint, requests):
            client = new_client(endpoint, max_batch_size=1)
            for content in ("one", "two"):
                client.capture({"conversation_id": "auth", "role": "user", "content": content})
            self.assertEqual(client.flush()["dropped"], 2)
            self.assertEqual(len(requests), 1)
            self.assertTrue(client.inspect()["disabled"])
            self.assertIsNone(client.capture({"conversation_id": "auth", "role": "user", "content": "three"}))

    def test_bounds_validation_and_callback_errors(self):
        client = new_client("http://127.0.0.1:9", max_queue_size=1)
        client.capture({"conversation_id": "queue", "role": "user", "content": "one"})
        self.assertIsNone(client.capture({"conversation_id": "queue", "role": "user", "content": "two"}))
        self.assertIsNone(client.capture({"conversation_id": "queue", "role": "tool", "content": "bad", "tokens": -1}))
        self.assertEqual(client.inspect()["drops"], {"queue_full": 1, "invalid_event": 1})
        redactor = new_client("http://127.0.0.1:9", redact=lambda _event: (_ for _ in ()).throw(ValueError("bad redactor")))
        self.assertIsNone(redactor.capture({"conversation_id": "redact", "role": "user", "content": "private"}))
        self.assertEqual(redactor.inspect()["drops"]["redaction"], 1)

    def test_real_turn_and_tool_spans_preserve_result_and_exception(self):
        with mock_api(lambda body, _attempt: (200, {"accepted": len(body["events"]), "duplicates": 0})) as (endpoint, requests):
            client = new_client(endpoint)
            result = {"text": "actual answer"}
            original = RuntimeError("actual failure")

            async def operate(trace):
                with client.span(trace, "tool", "lookup", {"query": "actual query"}) as span:
                    span.output = {"found": True}
                return result

            async def fail(trace):
                with client.span(trace, "tool", "failing_tool", {}):
                    raise original

            async def run():
                value = await client.with_turn({"conversation_id": "real"}, "actual input", operate, output=lambda output: output["text"])
                self.assertIs(value, result)
                try:
                    await client.with_turn({"conversation_id": "error"}, "failure request", fail)
                    self.fail("exception expected")
                except RuntimeError as error:
                    self.assertIs(error, original)

            asyncio.run(run())
            client.shutdown()
            events = requests[0]["body"]["events"]
            turn = next(event for event in events if event["conversation_id"] == "real" and event["role"] == "assistant")
            tool = next(event for event in events if event["conversation_id"] == "real" and event["role"] == "tool")
            self.assertEqual(tool["parent_span_id"], turn["span_id"])
            self.assertEqual(tool["trace_id"], turn["trace_id"])
            self.assertEqual(turn["content"], "actual answer")
            self.assertEqual(len([event for event in events if event["conversation_id"] == "error" and event.get("status") == "error"]), 2)

    def test_stream_turn_preserves_chunks_and_outcomes(self):
        with mock_api(lambda body, _attempt: (200, {"accepted": len(body["events"]), "duplicates": 0})) as (endpoint, requests):
            client = new_client(endpoint)

            def chunks():
                yield "Hel"
                yield "lo"

            seen = [chunk for chunk in client.stream_turn({"conversation_id": "stream"}, "Hi", chunks())]
            self.assertEqual(seen, ["Hel", "lo"])

            def failing():
                yield "part"
                raise RuntimeError("mid-stream failure")

            with self.assertRaises(RuntimeError):
                for _ in client.stream_turn({"conversation_id": "stream-err"}, "Hi", failing()):
                    pass

            def endless():
                yield "a"
                yield "b"

            for _ in client.stream_turn({"conversation_id": "stream-cancel"}, "Hi", endless()):
                break

            async def arun():
                async def achunks():
                    yield "x"
                    yield "y"
                return [chunk async for chunk in client.astream_turn({"conversation_id": "astream"}, "Hi", achunks())]

            self.assertEqual(asyncio.run(arun()), ["x", "y"])
            client.shutdown()
            events = requests[0]["body"]["events"]
            roles = [event["role"] for event in events if event["conversation_id"] == "stream"]
            self.assertEqual(roles, ["user", "assistant"])
            assistant = next(event for event in events if event["conversation_id"] == "stream" and event["role"] == "assistant")
            self.assertEqual(assistant["content"], "Hello")
            failed = next(event for event in events if event["conversation_id"] == "stream-err" and event["role"] == "assistant")
            self.assertEqual(failed["status"], "error")
            cancelled = next(event for event in events if event["conversation_id"] == "stream-cancel" and event["role"] == "assistant")
            self.assertEqual(cancelled["metadata"].get("stream_cancelled"), True)
            aassistant = next(event for event in events if event["conversation_id"] == "astream" and event["role"] == "assistant")
            self.assertEqual(aassistant["content"], "xy")


if __name__ == "__main__":
    unittest.main()
