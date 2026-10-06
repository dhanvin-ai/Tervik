"""Client parity tests for the packaged Python SDK (normal, stream, fail, parallel, retry, shutdown)."""
import asyncio
import json
import sys
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tervik import Tervik  # noqa: E402


@contextmanager
def mock_api(handler):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({"body": body, "path": self.path})
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
    options = {"api_key": "project-key", "endpoint": endpoint, "flush_interval": 0,
               "retry_base": 0, "on_drop": lambda _notice: None}
    options.update(kwargs)
    return Tervik(**options)


class SdkTests(unittest.TestCase):
    def test_normal_turn_and_tool(self):
        with mock_api(lambda body, _n: (200, {"accepted": len(body["events"]), "duplicates": 0})) as (endpoint, requests):
            client = new_client(endpoint)

            async def operate(trace):
                with client.span(trace, "tool", "lookup", {"q": "x"}) as span:
                    span.output = {"found": True}
                return {"text": "answer"}

            result = asyncio.run(client.with_turn({"conversation_id": "c"}, "hi", operate,
                                                  output=lambda value: value["text"]))
            self.assertEqual(result, {"text": "answer"})
            client.shutdown()
            events = requests[0]["body"]["events"]
            self.assertEqual([e["role"] for e in events], ["user", "tool", "assistant"])
            self.assertEqual(events[2]["content"], "answer")

    def test_streaming_failure_parallel_and_shutdown(self):
        with mock_api(lambda body, _n: (200, {"accepted": len(body["events"]), "duplicates": 0})) as (endpoint, requests):
            client = new_client(endpoint)

            def chunks():
                yield "a"
                yield "b"

            self.assertEqual(list(client.stream_turn({"conversation_id": "s"}, "hi", chunks())), ["a", "b"])

            def failing():
                yield "part"
                raise RuntimeError("boom")

            with self.assertRaises(RuntimeError):
                for _ in client.stream_turn({"conversation_id": "f"}, "hi", failing()):
                    pass

            def worker(index):
                client.capture({"conversation_id": f"p-{index}", "role": "user", "content": "hello"})

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            result = client.shutdown()
            self.assertEqual(result["pending"], 0)
            self.assertIsNone(client.capture({"conversation_id": "late", "role": "user", "content": "x"}))
            bodies = [r["body"]["events"] for r in requests]
            flat = [e for batch in bodies for e in batch]
            self.assertEqual(len([e for e in flat if e["conversation_id"] == "s"]), 2)
            self.assertTrue(any(e.get("status") == "error" for e in flat if e["conversation_id"] == "f"))

    def test_retries_keep_stable_ids(self):
        attempts = []

        def handler(body, _n):
            attempts.append([e["id"] for e in body["events"]])
            if len(attempts) < 3:
                return 503, {}
            return 200, {"accepted": len(body["events"]), "duplicates": 0}

        with mock_api(handler) as (endpoint, _requests):
            client = new_client(endpoint, max_retries=3)
            client.capture({"conversation_id": "r", "role": "user", "content": "hi"})
            result = client.flush()
            self.assertEqual(result["accepted"], 1)
            self.assertEqual(attempts[0], attempts[1])
            client.shutdown()


if __name__ == "__main__":
    unittest.main()
