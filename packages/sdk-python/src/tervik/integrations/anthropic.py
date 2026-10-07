"""Anthropic integration (messages API, streaming included).

Wraps a real client object without importing `anthropic`. Telemetry never
changes the response: content streams through untouched, original
exceptions are re-raised, tool_use blocks are recorded as tool spans, and
re-instrumenting the same client adds no duplicate capture.
"""
import time
import uuid

_MARKER = "tervik.instrumented"


def _text_blocks(content):
    if isinstance(content, str):
        return content, []
    texts, tools = [], []
    for block in content or []:
        kind = getattr(block, "type", None)
        if kind == "text":
            texts.append(getattr(block, "text", ""))
        elif kind == "tool_use":
            tools.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            texts.append(block.get("text", ""))
        elif isinstance(block, dict) and block.get("type") == "tool_use":
            tools.append(block)
    return "".join(texts), tools


def _tool_name_and_input(call):
    name = getattr(call, "name", None) or (call.get("name") if isinstance(call, dict) else None)
    arguments = getattr(call, "input", None)
    if arguments is None and isinstance(call, dict):
        arguments = call.get("input")
    return (str(name)[:200] if name else "tool"), arguments


def instrument_anthropic(tervik, client, *, conversation_id, user_id=None, model=None):
    """Patch `client.messages.create` to record turns. Returns `unpatch()`.
    Safe to call twice."""
    messages = getattr(client, "messages", None)
    if messages is None or not hasattr(messages, "create"):
        raise TypeError("client has no messages.create to instrument")
    if getattr(client, _MARKER, None) == id(tervik):
        return lambda: None
    original = messages.create

    def _context():
        return {"conversation_id": conversation_id, **({"user_id": user_id} if user_id else {})}

    def _user_text(kwargs, args):
        blocks = kwargs.get("messages", args[0] if args else [])
        parts = []
        for message in blocks:
            content = message.get("content", "") if isinstance(message, dict) else ""
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                parts.extend(b.get("text", "") for b in content
                             if isinstance(b, dict) and b.get("type") == "text")
        return " ".join(parts) or "anthropic.turn"

    def _record(turn_input, text, tool_calls, status, started, trace_id, span_id,
                response=None, error=None):
        content = text if status == "success" else str(error)
        usage = getattr(response, "usage", None) if response is not None else None
        tokens = None
        if usage is not None:
            incoming = getattr(usage, "input_tokens", 0) or 0
            outgoing = getattr(usage, "output_tokens", 0) or 0
            tokens = incoming + outgoing if incoming + outgoing > 0 else None
        event = {**_context(), "trace_id": trace_id, "span_id": span_id, "role": "assistant",
                 "name": "anthropic.turn", "status": status, "content": content[:32000],
                 "latency_ms": (time.perf_counter() - started) * 1000,
                 "model": getattr(response, "model", None) or model,
                 "metadata": {"input": turn_input, "output": content}}
        if tokens is not None:
            event["tokens"] = tokens
        tervik.capture(event)
        for call in tool_calls:
            name, arguments = _tool_name_and_input(call)
            tervik.capture({**_context(), "trace_id": trace_id, "span_id": str(uuid.uuid4()),
                            "parent_span_id": span_id, "role": "tool", "name": name,
                            "status": "success", "content": str(arguments)[:32000],
                            "metadata": {"input": arguments, "requested": True}})

    def create(*args, **kwargs):
        stream = kwargs.get("stream", False)
        turn_input = _user_text(kwargs, args)[:32000]
        trace_id, span_id, started = str(uuid.uuid4()), str(uuid.uuid4()), time.perf_counter()
        tervik.capture({**_context(), "trace_id": trace_id, "role": "user", "content": turn_input})
        try:
            response = original(*args, **kwargs)
        except BaseException as error:
            _record(turn_input, "", [], "error", started, trace_id, span_id, error=error)
            raise
        if stream:
            return _wrap_stream(response, turn_input, started, trace_id, span_id)
        text, tool_calls = _text_blocks(getattr(response, "content", None))
        _record(turn_input, text, tool_calls, "success", started, trace_id, span_id, response=response)
        return response

    def _wrap_stream(stream, turn_input, started, trace_id, span_id):
        texts, tool_calls, tool_index = [], [], {}
        try:
            for chunk in stream:
                try:
                    delta = getattr(chunk, "delta", None)
                    if getattr(delta, "text", None):
                        texts.append(delta.text)
                    partial = getattr(chunk, "content_block", None)
                    if getattr(partial, "type", None) == "tool_use":
                        tool_index[getattr(chunk, "index", 0)] = partial
                except AttributeError:
                    pass
                yield chunk
        except BaseException as error:
            _record(turn_input, "", [], "error", started, trace_id, span_id, error=error)
            raise
        tools = list(tool_index.values()) or tool_calls
        event_text = "".join(texts)
        tervik.capture({**_context(), "trace_id": trace_id, "span_id": span_id,
                        "role": "assistant", "name": "anthropic.turn", "status": "success",
                        "content": event_text[:32000],
                        "latency_ms": (time.perf_counter() - started) * 1000,
                        "model": model,
                        "metadata": {"input": turn_input, "output": event_text, "streamed": True}})
        for call in tools:
            name, arguments = _tool_name_and_input(call)
            tervik.capture({**_context(), "trace_id": trace_id, "span_id": str(uuid.uuid4()),
                            "parent_span_id": span_id, "role": "tool", "name": name,
                            "status": "success", "content": str(arguments)[:32000],
                            "metadata": {"input": arguments, "requested": True}})

    create.tervik_wrapped = True
    messages.create = create
    setattr(client, _MARKER, id(tervik))

    def unpatch():
        if getattr(messages.create, "tervik_wrapped", False):
            try:
                messages.create = original
            except AttributeError:
                pass
        try:
            delattr(client, _MARKER)
        except AttributeError:
            pass

    return unpatch
