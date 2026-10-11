"""Demo agents, instrumented with the Tervik SDK, for testing Tervik the way a
customer would: with a real model making real mistakes.

Two personas:
- general: a ChatGPT-style assistant for any question, with a calculator and
  a clock it uses only when a message asks for math or the time.
- shop: a support agent for a small shop whose tools behave like a real
  backend (some refunds are refused, the carrier API sometimes times out).

Each runs on a free local model through Ollama, or the OpenAI or Anthropic
API. Every turn and tool call is sent to Tervik with the SDK, and Tervik's
findings for the conversation are shown under each reply. To chat in the
browser instead, open Chat in the dashboard.

    npm run demo:agent                             # chat in the terminal (shop)
    npm run demo:agent -- --persona general        # chat in the terminal (general)
    npm run demo:agent -- --auto                   # scripted shop customers, then a report
    npm run demo:agent -- --provider anthropic     # use an API model instead of Ollama
"""
import argparse
import ast
import getpass
import json
import operator
import os
import random
import re
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime
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

# What Tervik's detectors mean, in the words shown after each reply.
FLAG_LABELS = {
    "correction": "You corrected the agent",
    "frustration": "You sounded frustrated",
    "repetition": "You repeated a request",
    "unresolved": "You said the problem isn't solved",
    "tool_error": "A tool call failed",
    "tool_timeout": "A tool call timed out",
    "unsupported_claim": "The agent claimed an action no tool performed",
    "rule_violation": "A behavior rule was broken",
    "policy_violation": "A policy was broken",
    "tool_bad_input": "A tool was called with made-up values",
    "unrequested_action": "The agent did something nobody asked for",
}


class ToolFailure(Exception):
    pass


# ---- personas ----

ORDERS = {
    "1001": {"item": "Wireless headphones", "status": "shipped", "tracking_id": "TRK-1001", "total": 89.99},
    "1002": {"item": "Running shoes", "status": "processing", "tracking_id": None, "total": 120.00},
    "1003": {"item": "Coffee grinder", "status": "delivered", "tracking_id": "TRK-1003", "total": 45.50},
}


def shop_tool(name, args, rng):
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


ARITHMETIC = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
              ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
              ast.USub: operator.neg, ast.UAdd: operator.pos}


def calculate(expression):
    """Arithmetic only: numbers, + - * / // % ** and parentheses."""
    text = str(expression).replace("×", "*").replace("÷", "/").replace("^", "**").replace(",", "")
    # "18%" means 18/100; "10 % 3" stays modulo.
    text = re.sub(r"(\d+(?:\.\d+)?)\s*%(?!\s*[\d(])", r"(\1/100)", text)

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in ARITHMETIC:
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ToolFailure("Exponent too large")
            return ARITHMETIC[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in ARITHMETIC:
            return ARITHMETIC[type(node.op)](walk(node.operand))
        raise ToolFailure(f"Not an arithmetic expression: {expression}")

    try:
        result = walk(ast.parse(text, mode="eval"))
    except ZeroDivisionError:
        raise ToolFailure("Division by zero")
    except SyntaxError:
        raise ToolFailure(f"Could not parse: {expression}")
    return {"expression": expression, "result": round(result, 10) if isinstance(result, float) else result}


def general_tool(name, args, rng):
    if name == "calculator":
        return calculate(args.get("expression", ""))
    if name == "get_current_time":
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        zone = str(args.get("timezone") or "UTC").strip()
        try:
            now = datetime.now(ZoneInfo(zone))
        except (ZoneInfoNotFoundError, ValueError):
            raise ToolFailure(f"Unknown time zone {zone}; use a name like Asia/Tokyo")
        return {"timezone": zone, "local_time": now.strftime("%A, %d %B %Y, %H:%M")}
    raise ToolFailure(f"Unknown tool {name}")


def tool(name, description, properties, required):
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}


PERSONAS = {
    "shop": {
        "agent": "shop-assistant", "project": "Demo agent",
        "system": ("You are the customer support assistant for Acme Shop.\n"
                   "Use the tools to look up orders, track packages, issue refunds, and cancel subscriptions.\n"
                   "Never say you did something unless a tool call confirmed it. Ask the customer to confirm "
                   "before issuing a refund.\nKeep replies short and friendly."),
        "tools": [tool("lookup_order", "Get an order's item, status, total, and tracking ID.", {"order_id": {"type": "string"}}, ["order_id"]),
                  tool("track_package", "Get a package's location and delivery estimate from the carrier.", {"tracking_id": {"type": "string"}}, ["tracking_id"]),
                  tool("refund_order", "Refund an order that has shipped or been delivered.",
                       {"order_id": {"type": "string"}, "reason": {"type": "string"}}, ["order_id", "reason"]),
                  tool("cancel_subscription", "Cancel the customer's Acme Plus subscription.", {"email": {"type": "string"}}, ["email"])],
        "run": shop_tool, "route": None,
        "intents": [("Track an order", "The customer wants to know where an order is.", ["where is my order", "track my package"]),
                    ("Get a refund", "The customer wants money back.", ["I want a refund", "refund my order"]),
                    ("Cancel a subscription", "The customer wants to stop a subscription.", ["cancel my subscription"])],
        "policies": [("Confirm before refunding", "The agent asks the customer to confirm before it issues a refund."),
                     ("Only state what tools returned", "Order, tracking, and refund details must come from a tool result.")],
    },
    "general": {
        "agent": "chat-assistant", "project": "Chat assistant",
        "system": "You are a helpful, friendly assistant. Answer any question clearly and concisely.",
        # Added only when the tools are on offer, so plain answers never mention them.
        "tool_hint": " For arithmetic, call the calculator and report its result. For the current date or time, call get_current_time.",
        "tools": [tool("calculator", "Evaluate an arithmetic expression such as (12.5 * 4) / 3.", {"expression": {"type": "string"}}, ["expression"]),
                  tool("get_current_time", "Get the current date and time in an IANA time zone such as Asia/Kolkata.",
                       {"timezone": {"type": "string"}}, ["timezone"])],
        "run": general_tool,
        # Small local models answer casual messages badly when tools are on
        # offer, so tools are offered only when a message asks for them.
        "route": re.compile(r"\d\s*[-+*/x×÷^%]\s*\d|\d\s*%|\b(calculate|compute|percent|square root|sqrt|divided by|times|"
                            r"plus|minus|how much is|what time|what's the time|time is it|time in|date today|"
                            r"today's date|what day)\b", re.I),
        "intents": [("Ask a question", "The user wants a fact or an explanation.", ["what is", "explain", "how does it work"]),
                    ("Get writing help", "The user wants text drafted or edited.", ["write a message", "rewrite this", "draft an email"]),
                    ("Do math", "The user wants a calculation.", ["what is 15% of 240", "calculate", "how much is"]),
                    ("Small talk", "The user is chatting casually.", ["hi", "how are you", "tell me a joke"])],
        "policies": [("Admit uncertainty", "When the assistant is not sure, it says so instead of presenting a guess as fact."),
                     ("Use tools for math and time", "Arithmetic results and the current time come from a tool call, not a guess.")],
    },
}


# ---- model calls ----

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

    def step(self, history, tools, system):
        if self.provider == "anthropic":
            body = {"model": self.model, "max_tokens": 1024, "system": system, "messages": history}
            if tools:
                body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
            reply = post(self.base + "/v1/messages", body, {"x-api-key": self.key, "anthropic-version": "2023-06-01"})
            text = "".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text")
            calls = [(b["id"], b["name"], b.get("input") or {}) for b in reply.get("content", []) if b.get("type") == "tool_use"]
            usage = reply.get("usage") or {}
            history.append({"role": "assistant", "content": reply.get("content", [])})
            return text, calls, (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
        body = {"model": self.model, "messages": [{"role": "system", "content": system}] + history}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
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


def looks_like_tool_stub(text):
    """Small models sometimes answer with an empty or malformed tool call."""
    stripped = (text or "").strip()
    return stripped.startswith("{") and (stripped == "{}" or '"name"' in stripped or '"parameters"' in stripped)


class Agent:
    def __init__(self, model, persona, rng):
        self.model, self.persona, self.rng = model, PERSONAS[persona], rng

    def answer(self, history, text, user_id, conversation_id, log=print):
        """One user message -> one Tervik turn with its tool calls nested under it.
        Returns (reply, tool records for display)."""
        turn = tervik.begin(user_id=user_id, agent_name=self.persona["agent"], input=text, conversation_id=conversation_id)
        turn.set_property("model", self.model.model)
        route = self.persona["route"]
        tools = self.persona["tools"] if route is None or route.search(text) else []
        start = len(history)
        history.append({"role": "user", "content": text})
        tokens, reply, used = 0, "", []
        try:
            for _ in range(6):
                system = self.persona["system"] + (self.persona.get("tool_hint", "") if tools else "")
                reply, calls, spent = self.model.step(history, tools, system)
                tokens += spent
                if not calls and tools and looks_like_tool_stub(reply):
                    del history[start + 1:]  # retry this message without tools
                    tools = []
                    continue
                if not calls:
                    break
                results = []
                for call_id, name, args in calls:
                    call = turn.tool(name, args)
                    try:
                        output = self.persona["run"](name, args, self.rng)
                        call.end(output)
                        results.append((call_id, json.dumps(output), False))
                        used.append({"name": name, "args": args, "ok": True, "output": json.dumps(output)[:300]})
                        log(f"    [tool] {name}({json.dumps(args)}) -> ok")
                    except ToolFailure as error:
                        call.end(f"Error: {error}", success=False)
                        results.append((call_id, f"Error: {error}", True))
                        used.append({"name": name, "args": args, "ok": False, "output": f"Error: {error}"})
                        log(f"    [tool] {name}({json.dumps(args)}) -> failed: {error}")
                self.model.add_results(history, results)
            turn.set_property("tokens", tokens)
            turn.end(reply or "(no reply)")
            return reply or "(no reply)", used
        except RuntimeError as error:
            turn.end(f"Model error: {error}", success=False)
            del history[start:]
            raise


# ---- Tervik ----

def fetch(api, path):
    """GET from Tervik, or None. Live checks must never stop the chat."""
    try:
        with urllib.request.urlopen(api + path, timeout=10) as response:
            return json.load(response)
    except (urllib.error.URLError, ValueError, OSError):
        return None


def new_flags(api, project_id, conversation_id, seen):
    """Send what the SDK has queued, then return Tervik's signals for this
    conversation that have not been shown yet."""
    tervik.flush()
    internal = str(uuid.uuid5(uuid.UUID(project_id), conversation_id))
    detail = fetch(api, f"/api/conversations/{internal}") or {}
    fresh = [s for s in detail.get("signals", []) if s["id"] not in seen]
    seen.update(s["id"] for s in fresh)
    return [{"kind": s["kind"], "label": FLAG_LABELS.get(s["kind"], s["kind"]), "reason": s["reason"]} for s in fresh]


def show_flags(flags):
    for flag in flags:
        print(f"    ⚑ Tervik: {flag['label']}. {flag['reason']}")


def list_problems(api, project_id, user_id):
    rows = fetch(api, f"/api/conversations?project_id={project_id}&range=30d&flagged=true") or []
    mine = [r for r in rows if r.get("user_id") == user_id]
    if not mine:
        print("No flagged conversations for you yet.\n")
        return
    print(f"Your flagged conversations ({len(mine)}):")
    for row in mine:
        labels = ", ".join(FLAG_LABELS.get(tag, tag) for tag in row["tags"])
        print(f"  - \"{row['preview'][:70]}\" ({row['message_count']} messages): {labels}")
    print("In the dashboard: Conversations, then turn on \"Problems only\".\n")


def tervik_project(api, persona):
    spec = PERSONAS[persona]
    existing = next((p for p in api_call(api, "GET", "/api/projects") if p["name"] == spec["project"]), None)
    if existing:
        return existing["id"]
    created = api_call(api, "POST", "/api/projects", {"name": spec["project"]})
    base = f'/api/projects/{created["id"]}'
    for name, description, examples in spec["intents"]:
        api_call(api, "POST", f"{base}/intents", {"name": name, "description": description, "examples": examples})
    for title, description in spec["policies"]:
        api_call(api, "POST", f"{base}/policies", {"title": title, "description": description})
    print(f'Created Tervik project "{spec["project"]}" with {len(spec["intents"])} intents and {len(spec["policies"])} policies.')
    return created["id"]


def pick_ollama_model(requested, base):
    """The requested model, or the default if installed, or any installed model."""
    if requested:
        return requested
    try:
        with urllib.request.urlopen(base.replace("/v1", "") + "/api/tags", timeout=5) as response:
            installed = [m["name"] for m in json.load(response).get("models", [])]
    except (urllib.error.URLError, ValueError, OSError):
        raise SystemExit("Ollama is not running. Start it with: brew services start ollama")
    if not installed:
        raise SystemExit("No Ollama models are installed. Download one with: ollama pull llama3.2")
    default = PROVIDERS["ollama"]["model"]
    return next((m for m in installed if m == default or m.split(":")[0] == default.split(":")[0]), installed[0])


# ---- terminal chat ----

SHOP_CUSTOMERS = [
    ["Hi, where is my order 1001?", "Can you track the package for me?"],
    ["I want a refund for order 1002, I don't need the shoes anymore", "This is frustrating, why can't I get my money back?"],
    ["Track package TRK-1003 please", "Track package TRK-1003 please"],
    ["My coffee grinder from order 1003 arrived broken. Refund it.", "Yes, I confirm. Please refund it."],
    ["Cancel my subscription, my email is sam@example.com", "No, I meant cancel it now, not at the end of the month"],
]


def run_terminal(agent, api, project_id, args):
    if args.auto:
        for index, messages in enumerate(SHOP_CUSTOMERS, 1):
            conversation_id, history, seen = str(uuid.uuid4()), [], set()
            print(f"--- Customer {index} ---")
            for text in messages:
                print(f"Customer: {text}")
                print(f"Agent:    {agent.answer(history, text, f'customer-{index}', conversation_id)[0]}")
                show_flags(new_flags(api, project_id, conversation_id, seen))
            print()
        return
    if args.persona == "shop":
        print("Chat with the shop assistant. Orders 1001 (shipped), 1002 (processing), and 1003 (delivered)")
        print("exist. Tervik's findings appear under each reply.")
    else:
        print("Chat about anything. Tervik's findings appear under each reply.")
    print("Commands: /new starts a new conversation, /problems lists your flagged ones, /quit ends.\n")
    conversation_id, history, seen = str(uuid.uuid4()), [], set()
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if text in ("/quit", "/exit"):
            return
        if text == "/new":
            conversation_id, history, seen = str(uuid.uuid4()), [], set()
            print("(new conversation)\n")
            continue
        if text == "/problems":
            tervik.flush()
            list_problems(api, project_id, args.user)
            continue
        if text:
            print(f"Agent: {agent.answer(history, text, args.user, conversation_id)[0]}")
            show_flags(new_flags(api, project_id, conversation_id, seen))
            print()


def main():
    sys.stdout.reconfigure(line_buffering=True)
    parser = argparse.ArgumentParser(description="Chat with a Tervik-instrumented demo agent")
    parser.add_argument("--persona", choices=sorted(PERSONAS), default="shop",
                        help="general (answers anything) or shop (support agent)")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), default=os.getenv("DEMO_PROVIDER", "ollama"))
    parser.add_argument("--model", default=None, help="Model name (defaults depend on the provider)")
    parser.add_argument("--base-url", default=None, help="Another OpenAI-compatible server, such as LM Studio")
    parser.add_argument("--auto", action="store_true", help="Play scripted shop customers instead of chatting")
    parser.add_argument("--api", default=os.getenv("TERVIK_ENDPOINT", "http://127.0.0.1:8000"))
    parser.add_argument("--user", default=getpass.getuser())
    parser.add_argument("--seed", type=int, default=None, help="Make tool failures repeatable")
    args = parser.parse_args()
    if args.auto:
        args.persona = "shop"
    preset = PROVIDERS[args.provider]
    key = os.getenv(preset["key"]) if preset["key"] else None
    if preset["key"] and not key:
        raise SystemExit(f"Set {preset['key']} to use {args.provider}, or use the free local model: --provider ollama")
    base = args.base_url or preset["base"]
    name = pick_ollama_model(args.model, base) if args.provider == "ollama" and not args.base_url else (args.model or preset["model"])
    model = Model(args.provider, name, base, key)
    api = args.api.rstrip("/")
    project_id = tervik_project(api, args.persona)
    agent = Agent(model, args.persona, random.Random(args.seed))
    tervik.init(project_id, endpoint=api, flush_interval=1.0)
    print(f"Agent model: {model.model} via {args.provider}. Tervik project: {PERSONAS[args.persona]['project']}.\n")
    try:
        run_terminal(agent, api, project_id, args)
    except RuntimeError as error:
        hint = "Is Ollama running? Start it with: brew services start ollama" if args.provider == "ollama" else ""
        print(f"\nThe model call failed: {error}. {hint}".rstrip())
    finally:
        tervik.shutdown()
    classify(api, project_id)
    report(api, project_id, PERSONAS[args.persona]["project"])


if __name__ == "__main__":
    main()
