"""Interaction API: begin()/end(), nested tool calls, track(), identify()."""
import json
import sys
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import tervik  # noqa: E402
from tervik import InteractionClient  # noqa: E402


@contextmanager
def mock_api(status_for=lambda path, n: 200):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({"path": self.path, "body": body, "headers": {k.lower(): v for k, v in self.headers.items()}})
            status = status_for(self.path, len(requests))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

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


def client(endpoint, **options):
    return InteractionClient("project-123", endpoint=endpoint, flush_interval=0, retry_base=0, **options)


class InteractionTests(unittest.TestCase):
    def test_turn_with_nested_tools_sends_session_first(self):
        with mock_api() as (endpoint, requests):
            sdk = client(endpoint)
            turn = sdk.begin(user_id="u-1", agent_name="support", input="Where is order 42?", conversation_id="c-1")
            turn.set_properties({"model": "gpt-4.1", "tokens": 150})
            with turn.tool("orders.lookup", {"order_id": 42}) as call:
                with call.tool("db.query", "select 1") as inner:
                    inner.output = [1]
                call.output = {"status": "shipped"}
            turn.end(output="It ships tomorrow.")
            turn.end(output="ignored")
            sdk.flush()
        paths = [r["path"] for r in requests]
        self.assertEqual(paths, ["/api/v1/capture-session"] + ["/api/v1/capture-event"] * 3)
        self.assertTrue(all(r["headers"]["x-org-id"] == "project-123" for r in requests))
        session = requests[0]["body"]
        self.assertEqual(session["session_id"], "c-1")
        self.assertEqual(session["user_data"], {"user_id": "u-1"})
        inner_event, tool_event, turn_event = (r["body"] for r in requests[1:])
        self.assertEqual(inner_event["parent_id"], tool_event["event_id"])
        self.assertEqual(tool_event["parent_id"], turn_event["event_id"])
        self.assertEqual(tool_event["args"], '{"order_id": 42}')
        self.assertEqual(turn_event["primitive_name"], "support")
        self.assertEqual(turn_event["result"], "It ships tomorrow.")
        self.assertNotIn("parent_id", turn_event)
        self.assertEqual(turn_event["metadata"], {"model": "gpt-4.1", "tokens": "150"})
        self.assertGreaterEqual(turn_event["latency"], 0)

    def test_failures_track_identify_and_lookup(self):
        with mock_api() as (endpoint, requests):
            sdk = client(endpoint, api_key="tvk_secret")
            sdk.track(user_id="u-2", input="hi", output="hello", agent_name="greeter", latency=12.5)
            sdk.identify("u-2", {"plan": "pro", "email": None})
            turn = sdk.begin(user_id="u-2", input="Pay invoice", interaction_id="req-1")
            self.assertIs(sdk.get_interaction("req-1"), turn)
            try:
                with turn.tool("payments.charge") as call:
                    raise TimeoutError("payment gateway timed out")
            except TimeoutError:
                pass
            sdk.get_interaction("req-1").end("Payment failed", success=False)
            self.assertIsNone(sdk.get_interaction("req-1"))
            sdk.flush()
        bodies = [(r["path"].rsplit("/", 1)[1], r["body"]) for r in requests]
        self.assertTrue(all(r["headers"]["authorization"] == "Bearer tvk_secret" for r in requests))
        tracked = next(b for kind, b in bodies if kind == "capture-event" and b["primitive_name"] == "greeter")
        self.assertEqual(tracked["latency"], 12.5)
        resent = [b for kind, b in bodies if kind == "capture-session" and b["user_data"].get("plan") == "pro"]
        self.assertEqual(len(resent), 2)  # the earlier session is updated, the new one carries the trait
        failed_tool = next(b for kind, b in bodies if kind == "capture-event" and b["primitive_name"] == "payments.charge")
        self.assertFalse(failed_tool["success"])
        self.assertIn("timed out", failed_tool["result"])
        failed_turn = next(b for kind, b in bodies if kind == "capture-event" and b["args"] == "Pay invoice")
        self.assertFalse(failed_turn["success"])

    def test_secrets_are_scrubbed_and_rejections_disable_capture(self):
        with mock_api(lambda path, n: 401) as (endpoint, requests):
            sdk = client(endpoint)
            sdk.track(user_id="u-3", input="my api_key=abc123secret", output="Bearer abcdefghijkl")
            sdk.flush()
            self.assertEqual(sdk.disabled, "authentication")
            sdk.track(user_id="u-3", input="later", output="later")
            sdk.flush()
        self.assertEqual(len(requests), 1)
        self.assertGreaterEqual(sdk.dropped, 2)

    def test_misconfiguration_never_raises(self):
        sdk = InteractionClient(None, api_key="", endpoint="ftp://nowhere", flush_interval=0)
        self.assertEqual(sdk.disabled, "configuration")
        turn = sdk.begin(user_id="u", input="x")
        turn.end("y")
        self.assertEqual(sdk.flush()["pending"], 0)

    def test_module_level_api(self):
        with mock_api() as (endpoint, requests):
            tervik.init("project-9", endpoint=endpoint, flush_interval=0, retry_base=0)
            tervik.identify("u-9", {"role": "admin"})
            tervik.track(user_id="u-9", input="hi", output="hello", conversation_id="c-9")
            tervik.shutdown()
        session = requests[0]["body"]
        self.assertEqual(session["user_data"], {"role": "admin", "user_id": "u-9"})
        self.assertEqual(requests[1]["body"]["session_id"], "c-9")


if __name__ == "__main__":
    unittest.main()
