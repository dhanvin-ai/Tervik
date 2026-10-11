"""Dashboard chat: talk to a model from the dashboard and watch Tervik check
every turn as it happens.

The chat runs an agent on a local Ollama model, or on the Anthropic or OpenAI
API when a key is configured, and records each turn through the same capture
pipeline as a customer's agent: the user's message and the reply as a turn
pair, with every tool call nested under it. Detection therefore sees chats
exactly as it sees production traffic, and the conversation, its problems,
and the project's overview update the moment a reply lands.

Two personas: a general assistant with a calculator and a clock, and a shop
support agent whose backend refuses some refunds and sometimes times out.
"""
import ast
from datetime import datetime
import json
import operator
import random
import re
import time
import urllib.error
import urllib.request
from uuid import UUID, uuid4, uuid5

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from . import capture_v1 as capture_mod
from .db import ConversationSession, Event, iso, utc

HISTORY_MESSAGES = 20
MAX_STEPS = 6


class ToolFailure(Exception):
    pass


class ModelUnavailable(Exception):
    pass


# ---- tools ----

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
    "general": {
        "name": "Assistant", "agent": "chat-assistant",
        "description": "Answers anything. Uses a calculator and a clock when asked for math or the time.",
        "system": "You are a helpful, friendly assistant. Answer any question clearly and concisely.",
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
        "ideas": ["Tell me a fun fact about space", "What is 18% of 2,450?", "What time is it in Tokyo?",
                  "Write a short birthday message for my friend"],
    },
    "shop": {
        "name": "Shop support", "agent": "shop-assistant",
        "description": "A store's support agent. Orders 1001 (shipped), 1002 (processing), 1003 (delivered); some tools fail.",
        "system": ("You are the customer support assistant for Acme Shop.\n"
                   "Use the tools to look up orders, track packages, issue refunds, and cancel subscriptions.\n"
                   "Never say you did something unless a tool call confirmed it. Ask the customer to confirm "
                   "before issuing a refund.\nKeep replies short and friendly."),
        "tool_hint": "",
        "tools": [tool("lookup_order", "Get an order's item, status, total, and tracking ID.", {"order_id": {"type": "string"}}, ["order_id"]),
                  tool("track_package", "Get a package's location and delivery estimate from the carrier.", {"tracking_id": {"type": "string"}}, ["tracking_id"]),
                  tool("refund_order", "Refund an order that has shipped or been delivered.",
                       {"order_id": {"type": "string"}, "reason": {"type": "string"}}, ["order_id", "reason"]),
                  tool("cancel_subscription", "Cancel the customer's Acme Plus subscription.", {"email": {"type": "string"}}, ["email"])],
        "run": shop_tool, "route": None,
        "ideas": ["Where is my order 1001?", "Refund order 1002 please", "Track package TRK-1003",
                  "Cancel my subscription"],
    },
}


# ---- models ----

def http_post(url, body, headers, timeout=180):
    request = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:200]
        error.close()
        raise ModelUnavailable(f"the model API returned HTTP {error.code}: {detail}")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ModelUnavailable(f"cannot reach the model ({getattr(error, 'reason', error)})")
    except ValueError:
        raise ModelUnavailable("the model API sent an unreadable reply")


def ollama_models(base_url, timeout=2.0):
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/api/tags", timeout=timeout) as response:
            return sorted(m["name"] for m in json.load(response).get("models", []))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError):
        return None


def available_models(settings):
    """Models the chat can use, and why the local ones are missing if they are."""
    models, note = [], None
    installed = ollama_models(settings.ollama_url)
    if installed is None:
        note = "Ollama is not running. Start it with: brew services start ollama"
    elif not installed:
        note = "No local models are installed. Download one with: ollama pull llama3.2"
    for name in installed or []:
        models.append({"id": f"ollama:{name}", "provider": "ollama", "name": name, "label": f"{name.removesuffix(':latest')} · local"})
    if settings.llm_api_key:
        models.append({"id": f"anthropic:{settings.llm_model}", "provider": "anthropic", "name": settings.llm_model,
                       "label": f"{settings.llm_model} · Anthropic"})
    if settings.openai_api_key:
        models.append({"id": f"openai:{settings.openai_model}", "provider": "openai", "name": settings.openai_model,
                       "label": f"{settings.openai_model} · OpenAI"})
    return models, note


class ChatModel:
    """One step against an OpenAI-compatible or Anthropic API. Returns
    (text, tool_calls, tokens); tool calls are (id, name, args)."""

    def __init__(self, provider, name, settings, transport=http_post):
        self.provider, self.name, self.transport = provider, name, transport
        if provider == "ollama":
            self.base, self.key = settings.ollama_url.rstrip("/") + "/v1", None
        elif provider == "openai":
            self.base, self.key = "https://api.openai.com/v1", settings.openai_api_key
        else:
            self.base, self.key = settings.llm_base_url, settings.llm_api_key

    def step(self, history, tools, system):
        if self.provider == "anthropic":
            body = {"model": self.name, "max_tokens": 1024, "system": system, "messages": history}
            if tools:
                body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
            reply = self.transport(self.base + "/v1/messages", body, {"x-api-key": self.key, "anthropic-version": "2023-06-01"})
            content = reply.get("content") or []
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            calls = [(b["id"], b["name"], b.get("input") or {}) for b in content if b.get("type") == "tool_use"]
            usage = reply.get("usage") or {}
            history.append({"role": "assistant", "content": content})
            return text, calls, (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
        body = {"model": self.name, "messages": [{"role": "system", "content": system}] + history}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        reply = self.transport(self.base + "/chat/completions", body, {"Authorization": f"Bearer {self.key}"} if self.key else {})
        message = (reply.get("choices") or [{}])[0].get("message") or {}
        calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            try:
                args = json.loads(function.get("arguments") or "{}")
            except ValueError:
                args = {}
            calls.append((call.get("id") or str(uuid4()), function.get("name", ""), args if isinstance(args, dict) else {}))
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


def now_ms():
    return int(time.time() * 1000)


def run_turn(model, persona, history, text, rng):
    """Answer one message. Returns the reply, the tool calls it made (with
    timing), and the tokens used. Raises ModelUnavailable."""
    spec = PERSONAS[persona]
    tools = spec["tools"] if spec["route"] is None or spec["route"].search(text) else []
    start = len(history)
    history.append({"role": "user", "content": text})
    tokens, reply, calls_made = 0, "", []
    for _ in range(MAX_STEPS):
        system = spec["system"] + (spec["tool_hint"] if tools else "")
        reply, calls, spent = model.step(history, tools, system)
        tokens += spent
        if not calls and tools and looks_like_tool_stub(reply):
            del history[start + 1:]  # retry this message without tools
            tools = []
            continue
        if not calls:
            break
        results = []
        for call_id, name, args in calls:
            started = now_ms()
            try:
                output, ok = spec["run"](name, args, rng), True
                text_out = json.dumps(output)
            except ToolFailure as error:
                ok, text_out = False, f"Error: {error}"
            calls_made.append({"id": str(uuid4()), "name": name or "tool", "args": args, "ok": ok, "output": text_out,
                               "started": started, "latency": max(0, now_ms() - started)})
            results.append((call_id, text_out, not ok))
        model.add_results(history, results)
    return reply.strip() or "(no reply)", calls_made, tokens


# ---- routes ----

class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=64)
    persona: str = Field(default="general", pattern="^(general|shop)$")
    model: str | None = Field(default=None, max_length=200)


def conversation_uuid(project_id, session_id):
    return str(uuid5(UUID(project_id), session_id))


def register(app, *, sessions, settings, write_project, read_project, project_signals, record_event, finish_events):
    rng = random.Random()

    def models():
        override = getattr(app.state, "playground_models", None)
        return override() if override else available_models(settings)

    @app.get("/api/playground/status")
    def playground_status():
        options, note = models()
        return {"models": options, "default_model": options[0]["id"] if options else None, "note": note,
                "personas": [{"id": key, "name": spec["name"], "description": spec["description"], "ideas": spec["ideas"]}
                             for key, spec in PERSONAS.items()]}

    @app.get("/api/projects/{id}/playground/chats")
    def playground_chats(request: Request, id: str):
        with sessions() as db_session:
            read_project(request, db_session, id)
            rows = [row for row in db_session.scalars(select(ConversationSession).where(
                ConversationSession.project_id == id).order_by(ConversationSession.updated_at.desc()))
                if (row.session_metadata or {}).get("source") == "playground"][:50]
            _, signals = project_signals(db_session, id)
            flagged = {}
            for signal in signals:
                flagged.setdefault(signal["conversation_id"], set()).add(signal["kind"])
            chats = []
            for row in rows:
                first = db_session.scalars(select(Event.content).where(
                    Event.project_id == id, Event.conversation_id == row.conversation_id, Event.role == "user")
                    .order_by(Event.timestamp, Event.id).limit(1)).first()
                if first is None:
                    continue
                chats.append({"session_id": row.id, "conversation_id": row.conversation_id,
                              "title": " ".join(first.split())[:60] or "New chat",
                              "persona": (row.session_metadata or {}).get("persona", "general"),
                              "problems": sorted(flagged.get(row.conversation_id, set())),
                              "updated_at": iso(row.updated_at)})
            return chats

    @app.post("/api/projects/{id}/playground/chat")
    def playground_chat(request: Request, id: str, body: ChatInput):
        options, note = models()
        choice = next((m for m in options if m["id"] == body.model), options[0] if options and not body.model else None)
        if choice is None:
            raise HTTPException(424, note or "That model is not available. Pick another one.")
        transport = getattr(app.state, "playground_transport", None) or http_post
        model = ChatModel(choice["provider"], choice["name"], settings, transport)
        session_id = body.session_id or f"chat-{uuid4()}"
        with sessions() as db_session:
            project, _ = write_project(request, db_session, id, "member")
            conversation_id = conversation_uuid(project.id, session_id)
            earlier = list(db_session.scalars(select(Event).where(
                Event.project_id == project.id, Event.conversation_id == conversation_id,
                Event.role.in_(("user", "assistant"))).order_by(Event.timestamp, Event.id)))
        history = [{"role": e.role, "content": e.content} for e in earlier if e.content][-HISTORY_MESSAGES:]
        while history and history[0]["role"] != "user":
            history.pop(0)
        started = now_ms()
        try:
            reply, calls, tokens = run_turn(model, body.persona, history, body.message.strip(), rng)
        except ModelUnavailable as error:
            hint = " Is Ollama running? Start it with: brew services start ollama" if choice["provider"] == "ollama" else ""
            raise HTTPException(424, f"The model call failed: {error}.{hint}")
        latency = max(0, now_ms() - started)
        user_id = "dashboard-chat"
        turn_id = str(uuid4())
        recorded = []
        with sessions.begin() as db_session:
            project, _ = write_project(request, db_session, id, "member")
            capture_mod.upsert_session(db_session, project.id, capture_mod.SessionCapture(
                session_id=session_id, user_data={"user_id": user_id},
                metadata={"source": "playground", "persona": body.persona, "model": choice["name"]},
                timestamp=started, client_config="tervik-dashboard-chat"))
            turn = capture_mod.EventCapture(
                event_id=turn_id, session_id=session_id, primitive_name=PERSONAS[body.persona]["agent"],
                args=body.message.strip(), result=reply, success=True, latency=latency, timestamp=started,
                metadata={"model": choice["name"], "tokens": str(tokens), "source": "playground"})
            recorded.append((turn_id, record_event(db_session, project, "production", turn)))
            for call in calls:
                event = capture_mod.EventCapture(
                    event_id=call["id"], session_id=session_id, primitive_name=call["name"], args=call["args"],
                    result=call["output"], success=call["ok"], latency=call["latency"], timestamp=call["started"],
                    parent_id=turn_id, metadata={"source": "playground"})
                recorded.append((call["id"], record_event(db_session, project, "production", event)))
        finish_events(project.id, recorded)
        return {"session_id": session_id, "conversation_id": conversation_id, "reply": reply,
                "model": choice["id"], "tools": [{k: call[k] for k in ("name", "args", "ok", "output")} for call in calls]}
