"""OpenAI integration (chat.completions and responses, streaming included).

Wraps a real client object without importing `openai`, so any compatible
version works. Telemetry never changes the response: results stream
through untouched, original exceptions are re-raised, and re-instrumenting
the same client adds no duplicate capture.
"""
import time
import uuid

_MARKER = "tervik.instrumented"


def _message_text(message):
    if message is None:
        return ""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return "" if content is None else str(content)


def _usage(response):
    usage = getattr(response, "usage", None)
    tokens = getattr(usage, "total_tokens", None) if usage is not None else None
    return tokens if isinstance(tokens, int) and tokens >= 0 else None


def _model(response, fallback=None):
    model = getattr(response, "model", None)
    return model if isinstance(model, str) and model else fallback


def _tool_spans(tervik, context, trace_id, message):
    tool_calls = getattr(message, "tool_calls", None) or []
    for call in tool_calls:
        function = getattr(call, "function", None)
        name = getattr(function, "name", None) or getattr(call, "name", None) or "tool"
        arguments = getattr(function, "arguments", None)
        if arguments is None and isinstance(call, dict):
            name = call.get("name", name)
            arguments = call.get("arguments")
        span_id = str(uuid.uuid4())
        tervik.capture({**context, "trace_id": trace_id, "span_id": span_id,
                        "parent_span_id": context.get("parent_span_id"),
                        "role": "tool", "name": str(name)[:200], "status": "success",
                        "content": str(arguments)[:32000] if arguments is not None else "",
                        "metadata": {"input": arguments, "requested": True}})


def instrument_openai(tervik, client, *, conversation_id, user_id=None, model=None):
    """Patch `client.chat.completions.create` (and `responses.create` when
    present) to record turns. Returns an `unpatch()` callable. Safe to call
    twice: the second call is a no-op returning the same restore function."""
    targets = []
    chat = getattr(getattr(client, "chat", None), "completions", None)
    if chat is not None and hasattr(chat, "create"):
        targets.append((chat, "create", "chat"))
    responses = getattr(client, "responses", None)
    if responses is not None and hasattr(responses, "create"):
        targets.append((responses, "create", "responses"))
    if not targets:
        raise TypeError("client has neither chat.completions.create nor responses.create")
    if getattr(client, _MARKER, None) == id(tervik):
        return lambda: None
    originals = [(target, name, getattr(target, name)) for target, name, _ in targets]

    def _context():
        return {"conversation_id": conversation_id, **({"user_id": user_id} if user_id else {})}

    def _record(turn_input, text, status, started, trace_id, span_id, response=None, error=None):
        content = text if status == "success" else str(error)
        metadata = {"input": turn_input, "output": content}
        tokens = _usage(response) if response is not None else None
        event = {**_context(), "trace_id": trace_id, "span_id": span_id, "role": "assistant",
                 "name": "openai.turn", "status": status, "content": content[:32000],
                 "latency_ms": (time.perf_counter() - started) * 1000,
                 "model": _model(response, model), "metadata": metadata}
        if tokens is not None:
            event["tokens"] = tokens
        tervik.capture(event)
        if status == "success" and response is not None:
            message = getattr(response, "choices", [None])[0] if hasattr(response, "choices") else None
            message = getattr(message, "message", message)
            if message is None and hasattr(response, "output_text"):
                message = response.output_text
            _tool_spans(tervik, {**_context(), "parent_span_id": span_id}, trace_id, message)

    def _wrap(original, kind):
        if kind == "chat":
            def create(*args, **kwargs):
                stream = kwargs.get("stream", False)
                messages = kwargs.get("messages", args[0] if args else [])
                turn_input = " ".join(m.get("content", "") for m in messages if isinstance(m, dict)) or kind
                trace_id, span_id, started = str(uuid.uuid4()), str(uuid.uuid4()), time.perf_counter()
                tervik.capture({**_context(), "trace_id": trace_id, "role": "user", "content": turn_input[:32000]})
                try:
                    response = original(*args, **kwargs)
                except BaseException as error:
                    _record(turn_input, "", "error", started, trace_id, span_id, error=error)
                    raise
                if stream:
                    return _wrap_stream(response, turn_input, started, trace_id, span_id)
                message = response.choices[0].message
                _record(turn_input, _message_text(message), "success", started, trace_id, span_id, response=response)
                return response
        else:
            def create(*args, **kwargs):
                turn_input = kwargs.get("input", args[0] if args else kind)
                if not isinstance(turn_input, str):
                    turn_input = str(turn_input)
                trace_id, span_id, started = str(uuid.uuid4()), str(uuid.uuid4()), time.perf_counter()
                tervik.capture({**_context(), "trace_id": trace_id, "role": "user", "content": turn_input[:32000]})
                try:
                    response = original(*args, **kwargs)
                except BaseException as error:
                    _record(turn_input, "", "error", started, trace_id, span_id, error=error)
                    raise
                _record(turn_input, getattr(response, "output_text", ""), "success", started, trace_id, span_id, response=response)
                return response
        create.tervik_wrapped = True
        return create

    def _wrap_stream(stream, turn_input, started, trace_id, span_id):
        text_parts, response = [], None
        try:
            for chunk in stream:
                try:
                    delta = chunk.choices[0].delta
                    if getattr(delta, "content", None):
                        text_parts.append(delta.content)
                    if getattr(delta, "tool_calls", None):
                        text_parts.append(str(delta.tool_calls))
                except (AttributeError, IndexError):
                    pass
                yield chunk
        except BaseException as error:
            _record(turn_input, "", "error", started, trace_id, span_id, error=error)
            raise
        text = "".join(text_parts)
        event = {**_context(), "trace_id": trace_id, "span_id": span_id, "role": "assistant",
                 "name": "openai.turn", "status": "success", "content": text[:32000],
                 "latency_ms": (time.perf_counter() - started) * 1000,
                 "model": model, "metadata": {"input": turn_input, "output": text, "streamed": True}}
        tervik.capture(event)

    for (target, name, original), (_, _, kind) in zip(originals, targets):
        setattr(target, name, _wrap(original, kind))
    setattr(client, _MARKER, id(tervik))

    def unpatch():
        for target, name, original in originals:
            if getattr(target, name, None) is not original and not getattr(getattr(target, name), "tervik_wrapped", False):
                continue
            try:
                setattr(target, name, original)
            except AttributeError:
                pass
        try:
            delattr(client, _MARKER)
        except AttributeError:
            pass

    return unpatch
