"""Send realistic conversations to a running Tervik through the Python SDK.

Creates a project with an intent and a policy, records a handful of agent
turns and tool calls (some succeed, some fail in the ways Tervik detects),
runs classification, and prints where to look.

Usage (with `npm run dev` running):
    python3 scripts/try_agent.py [--api http://127.0.0.1:8000]
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "sdk-python" / "src"))

import tervik  # noqa: E402


def call(api, method, path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(api + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise SystemExit(f"{method} {path} failed with HTTP {error.code}: {error.read().decode()[:300]}")
    except urllib.error.URLError:
        raise SystemExit(f"Cannot reach {api}. Start Tervik first with: npm run dev")


def converse(user_id, plan, turns):
    """One conversation: each turn is (input, output, success, tools)."""
    conversation_id = str(uuid.uuid4())
    tervik.identify(user_id, {"plan": plan})
    for user_text, reply, success, tools in turns:
        turn = tervik.begin(user_id=user_id, agent_name="support-agent", input=user_text,
                            conversation_id=conversation_id)
        turn.set_property("model", "gpt-4.1")
        for name, given, output, ok in tools:
            call_ = turn.tool(name, given)
            time.sleep(0.01)
            call_.end(output=output, success=ok)
        turn.end(output=reply, success=success)


def main():
    parser = argparse.ArgumentParser(description="Send sample agent traffic to Tervik")
    parser.add_argument("--api", default=os.getenv("TERVIK_ENDPOINT", "http://127.0.0.1:8000"))
    args = parser.parse_args()
    api, token = args.api.rstrip("/"), os.getenv("TERVIK_ADMIN_TOKEN") or None

    project = call(api, "POST", "/api/projects", {"name": f"Try agent {time.strftime('%H:%M:%S')}"}, token)
    base = f'/api/projects/{project["id"]}'
    call(api, "POST", f"{base}/intents", {"name": "Track an order", "description": "The user wants to know where an order is.",
                                          "examples": ["Where is my order?", "Track my package", "When will my order arrive?"]}, token)
    call(api, "POST", f"{base}/intents", {"name": "Get a refund", "description": "The user wants money back.",
                                          "examples": ["I want a refund", "Refund my order", "Can I get my money back?"]}, token)
    call(api, "POST", f"{base}/policies", {"title": "Never reveal full card numbers",
                                           "description": "Show at most the last four digits of a card."}, token)

    tervik.init(project["id"], endpoint=api, flush_interval=0)
    converse("user-ana", "pro", [
        ("Where is my order 1042?", "Order 1042 shipped and arrives tomorrow.", True,
         [("orders.lookup", {"order_id": 1042}, {"status": "shipped", "eta": "tomorrow"}, True)])])
    converse("user-ben", "free", [
        ("Track my package 77", "Sorry, I could not reach the shipping service.", False,
         [("shipping.track", {"package": 77}, "Error: request timed out after 30s", False)]),
        ("Track my package 77", "Still unavailable, please try later.", False,
         [("shipping.track", {"package": 77}, "Error: request timed out after 30s", False)])])
    converse("user-cara", "pro", [
        ("I want a refund for order 88", "Done! I've refunded order 88 to the card 4111 1111 1111 1111.", True, [])])
    converse("user-dev", "free", [
        ("Cancel my subscription", "Your plan renews on the 1st.", True, []),
        ("That's wrong, I asked you to cancel it", "Sorry about that. Your subscription is cancelled.", True,
         [("billing.cancel", {"user": "user-dev"}, {"cancelled": True}, True)])])
    converse("user-eli", "pro", [
        ("Can I get my money back for order 12?", "Refund for order 12 is on its way.", True,
         [("payments.refund", {"order_id": 12}, {"refund_id": "rf_12"}, True)])])
    converse("user-fay", "free", [
        ("Change my delivery address", "This is not working, the form keeps failing", False,
         [("orders.update_address", {"order_id": 5}, "Error: validation failed: postcode", False)]),
        ("This is frustrating, it still doesn't work", "I've escalated this to a human agent.", True, [])])
    result = tervik.shutdown()
    print(f"Sent {result['sent']} capture requests ({result['dropped']} dropped).")

    run = call(api, "POST", f"{base}/classify", {"range": "24h"}, token)
    summary = call(api, "GET", f"{base}/summary?range=24h", token=token)
    print(f"Classified {run['analyzed']} conversations with {run['classifier']}"
          + (f" ({run['model']})." if run.get("model") else ". Set ANTHROPIC_API_KEY to check policies with an LLM."))
    print(f"\nProject: {project['name']} ({project['id']})")
    print(f"{summary['total_conversations']} conversations, {summary['total_calls']} calls, "
          f"{summary['success_rate']}% succeeded.")
    print("\nOpen the dashboard and pick this project in the sidebar: http://127.0.0.1:5173/#overview")
    print(f"Explore the new API at http://127.0.0.1:8000/docs, for example:")
    for path in ("summary", "tools", "events", "errors", "users", "intent-stats", "violations"):
        print(f"  curl -s '{api}{base}/{path}?range=24h'")


if __name__ == "__main__":
    main()
