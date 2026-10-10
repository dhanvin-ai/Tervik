"""A small shop-support agent, instrumented with the Tervik SDK, for testing
Tervik the way a customer would: with a real model making real mistakes.

It runs on a free local model through Ollama, or on the OpenAI or Anthropic
API. Its tools behave like a real backend: some orders cannot be refunded and
the carrier API sometimes times out. Chat with it, try to confuse it, and
watch Tervik catch what goes wrong.

    npm run demo:agent                       # chat in the terminal (Ollama by default)
    npm run demo:agent -- --auto             # play scripted customers, then report
    npm run demo:agent -- --provider anthropic
    npm run demo:agent -- --provider openai --model <model>
"""
import argparse
import getpass
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "sdk-python" / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import tervik  # noqa: E402
from import_chats import api_call, classify, report  # noqa: E402

PROVIDERS = {
    "ollama": {"base": "http://127.0.0.1:11434/v1", "model": "qwen2.5:7b", "key": None},
    "openai": {"base": "https://api.openai.com/v1", "model": "gpt-4.1-mini", "key": "OPENAI_API_KEY"},
    "anthropic": {"base": "https://api.anthropic.com", "model": "claude-opus-5-5", "key": "ANTHROPIC_API_KEY"},
}

SYSTEM = """You are the customer support assistant for Acme Shop.
Use the tools to look up orders, track packages, issue refunds, and cancel subscriptions.
Never say you did something unless a tool call confirmed it. Ask the customer to confirm before issuing a refund.
Keep replies short and friendly."""

ORDERS = {
    "1001": {"item": "Wireless headphones", "status": "shipped", "tracking_id": "TRK-1001", "total": 89.99},
    "1002": {"item": "Running shoes", "status": "processing", "tracking_id": None, "total": 120.00},
    "1003": {"item": "Coffee grinder", "status": "delivered", "tracking_id": "TRK-1003", "total": 45.50},
}

TOOLS = [
    {"name": "lookup_order", "description": "Get an order's item, status, total, and tracking ID.",
     "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}},
    {"name": "track_package", "description": "Get a package's location and delivery estimate from the carrier.",
     "parameters": {"type": "object", "properties": {"tracking_id": {"type": "string"}}, "required": ["tracking_id"]}},
    {"name": "refund_order", "description": "Refund an order that has shipped or been delivered.",
     "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}, "reason": {"type": "string"}},
                    "required": ["order_id", "reason"]}},
    {"name": "cancel_subscription", "description": "Cancel the customer's Acme Plus subscription.",
     "parameters": {"type": "object", "properties": {"email": {"type": "string"}}, "required": ["email"]}},
]

CUSTOMERS = [
    ["Hi, where is my order 1001?", "Can you track the package for me?"],
    ["I want a refund for order 1002, I don't need the shoes anymore", "This is frustrating, why can't I get my money back?"],
    ["Track package TRK-1003 please", "Track package TRK-1003 please"],
    ["My coffee grinder from order 1003 arrived broken. Refund it.", "Yes, I confirm. Please refund it."],
    ["Cancel my subscription, my email is sam@example.com", "No, I meant cancel it now, not at the end of the month"],
]


class ToolFailure(Exception):
    pass


def run_tool(name, args, rng):
    order_id = str(args.get("order_id", "")).strip().lstrip("#")
    if name == "lookup_order":
        if order_id not in ORDERS:
            raise ToolFailure(f"Order {order_id or '?'} not found")
        return {"order_id": order_id, **ORDERS[order_id]}
    if name == "track_package":
        if rng.random() < 0.35:
            raise ToolFailure("Carrier API timed out after 30s")
        tracking = str(args.get("tracking_id", ""))
        if not any(o["tracking_id"] == tracking for o in ORDERS.values()):
            raise ToolFailure(f"Unknown tracking ID {tracking or '?'}")
        return {"tracking_id": tracking, "location": "Regional hub, Pune", "estimated_delivery": "in 2 days"}
    if name == "refund_order":
        order = ORDERS.get(order_id)
        if order is None:
            raise ToolFailure(f"Order {order_id or '?'} not found")
        if order["status"] == "processing":
            raise ToolFailure("Cannot refund an order that has not shipped; cancel it instead")
        return {"order_id": order_id, "refunded": order["total"], "refund_id": f"rf_{order_id}"}
    if name == "cancel_subscription":
        return {"email": args.get("email"), "status": "cancels at the end of the billing period"}
    raise ToolFailure(f"Unknown tool {name}")


def post(url, body, headers, timeout=180):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers},
                                     method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"model API returned HTTP {error.code}: {error.read().decode()[:200]}")
    except urllib.error.URLError as error:
        raise RuntimeError(f"cannot reach the model API ({error.reason})")


class Model:
    """One chat step against an OpenAI-compatible or Anthropic API.
    Returns (text, tool_calls, tokens); tool calls are (id, name, args)."""

    def __init__(self, provider, model, base, key):
        self.provider, self.model, self.base, self.key = provider, model, base.rstrip("/"), key

    def step(self, history):
        if self.provider == "anthropic":
            body = {"model": self.model, "max_tokens": 1024, "system": SYSTEM, "messages": history,
                    "tools": [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in TOOLS]}
            reply = post(self.base + "/v1/messages", body, {"x-api-key": self.key, "anthropic-version": "2023-06-01"})
            text = "".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text")
            calls = [(b["id"], b["name"], b.get("input") or {}) for b in reply.get("content", []) if b.get("type") == "tool_use"]
            usage = reply.get("usage") or {}
            history.append({"role": "assistant", "content": reply.get("content", [])})
            return text, calls, (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
        body = {"model": self.model, "messages": [{"role": "system", "content": SYSTEM}] + history,
                "tools": [{"type": "function", "function": t} for t in TOOLS]}
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        reply = post(self.base + "/chat/completions", body, headers)
        message = (reply.get("choices") or [{}])[0].get("message") or {}
        calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            try:
                args = json.loads(function.get("arguments") or "{}")
            except ValueError:
                args = {}
            calls.append((call.get("id") or str(uuid.uuid4()), function.get("name", ""), args if isinstance(args, dict) else {}))
        history.append({"role": "assistant", "content": message.get("content") or "",
                        **({"tool_calls": message["tool_calls"]} if message.get("tool_calls") else {})})
        return message.get("content") or "", calls, (reply.get("usage") or {}).get("total_tokens") or 0

    def add_results(self, history, results):
        if self.provider == "anthropic":
            history.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": id, "content": text,
                                                         **({"is_error": True} if failed else {})}
                                                        for id, text, failed in results]})
        else:
            history.extend({"role": "tool", "tool_call_id": id, "content": text} for id, text, _ in results)


def answer(model, history, text, user_id, conversation_id, rng):
    """One customer message -> one Tervik turn with its tool calls nested under it."""
    turn = tervik.begin(user_id=user_id, agent_name="shop-assistant", input=text, conversation_id=conversation_id)
    turn.set_property("model", model.model)
    history.append({"role": "user", "content": text})
    tokens, reply = 0, ""
    try:
        for _ in range(6):
            reply, calls, used = model.step(history)
            tokens += used
            if not calls:
                break
            results = []
            for call_id, name, args in calls:
                call = turn.tool(name, args)
                try:
                    output = run_tool(name, args, rng)
                    call.end(output)
                    results.append((call_id, json.dumps(output), False))
                    print(f"    [tool] {name}({json.dumps(args)}) -> ok")
                except ToolFailure as error:
                    call.end(f"Error: {error}", success=False)
                    results.append((call_id, f"Error: {error}", True))
                    print(f"    [tool] {name}({json.dumps(args)}) -> failed: {error}")
            model.add_results(history, results)
        turn.set_property("tokens", tokens)
        turn.end(reply or "(no reply)")
        return reply
    except RuntimeError as error:
        turn.end(f"Model error: {error}", success=False)
        raise


def demo_project(api):
    existing = next((p for p in api_call(api, "GET", "/api/projects") if p["name"] == "Demo agent"), None)
    if existing:
        return existing["id"]
    created = api_call(api, "POST", "/api/projects", {"name": "Demo agent"})
    base = f'/api/projects/{created["id"]}'
    for name, description, examples in [
            ("Track an order", "The customer wants to know where an order is.", ["where is my order", "track my package"]),
            ("Get a refund", "The customer wants money back.", ["I want a refund", "refund my order"]),
            ("Cancel a subscription", "The customer wants to stop a subscription.", ["cancel my subscription"])]:
        api_call(api, "POST", f"{base}/intents", {"name": name, "description": description, "examples": examples})
    for title, description in [
            ("Confirm before refunding", "The agent asks the customer to confirm before it issues a refund."),
            ("Only state what tools returned", "Order, tracking, and refund details must come from a tool result.")]:
        api_call(api, "POST", f"{base}/policies", {"title": title, "description": description})
    print('Created project "Demo agent" with 3 intents and 2 policies.')
    return created["id"]


def main():
    sys.stdout.reconfigure(line_buffering=True)
    parser = argparse.ArgumentParser(description="Chat with a Tervik-instrumented demo agent")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), default=os.getenv("DEMO_PROVIDER", "ollama"))
    parser.add_argument("--model", default=None, help="Model name (defaults depend on the provider)")
    parser.add_argument("--base-url", default=None, help="Another OpenAI-compatible server, such as LM Studio")
    parser.add_argument("--auto", action="store_true", help="Play scripted customers instead of chatting")
    parser.add_argument("--api", default=os.getenv("TERVIK_ENDPOINT", "http://127.0.0.1:8000"))
    parser.add_argument("--user", default=getpass.getuser())
    parser.add_argument("--seed", type=int, default=None, help="Make tool failures repeatable")
    args = parser.parse_args()
    preset = PROVIDERS[args.provider]
    key = os.getenv(preset["key"]) if preset["key"] else None
    if preset["key"] and not key:
        raise SystemExit(f"Set {preset['key']} to use {args.provider}, or use the free local model: --provider ollama")
    model = Model(args.provider, args.model or preset["model"], args.base_url or preset["base"], key)
    api, rng = args.api.rstrip("/"), random.Random(args.seed)
    project_id = demo_project(api)
    tervik.init(project_id, endpoint=api, flush_interval=1.0)
    print(f"Agent model: {model.model} via {args.provider}. Tervik project: Demo agent.\n")
    try:
        if args.auto:
            for index, messages in enumerate(CUSTOMERS, 1):
                conversation_id, history = str(uuid.uuid4()), []
                print(f"--- Customer {index} ---")
                for text in messages:
                    print(f"Customer: {text}")
                    print(f"Agent:    {answer(model, history, text, f'customer-{index}', conversation_id, rng)}")
                print()
        else:
            print("Chat with the shop assistant. Try order 1001, 1002, or 1003. Commands: /new, /quit\n")
            conversation_id, history = str(uuid.uuid4()), []
            while True:
                try:
                    text = input("You: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if text in ("/quit", "/exit"):
                    break
                if text == "/new":
                    conversation_id, history = str(uuid.uuid4()), []
                    print("(new conversation)\n")
                    continue
                if text:
                    print(f"Agent: {answer(model, history, text, args.user, conversation_id, rng)}\n")
    except RuntimeError as error:
        hint = "Is Ollama running? Start the Ollama app, or run: ollama serve" if args.provider == "ollama" else ""
        print(f"\nThe model call failed: {error}. {hint}".rstrip())
    finally:
        tervik.shutdown()
    classify(api, project_id)
    report(api, project_id, "Demo agent")


if __name__ == "__main__":
    main()
