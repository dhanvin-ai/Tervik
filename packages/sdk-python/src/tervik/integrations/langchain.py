"""LangChain / LangGraph integration via a callback handler.

Pass `TervikCallbackHandler` in callbacks (or `config={"callbacks": [...]}`)
of a real chain/agent. LLM and tool activity is recorded with shared trace
ids and parent linkage. Re-delivered runs (same run id) are recorded once,
so retries and replays never create duplicate event streams.
"""
import time
import uuid


def _text(value, limit=32000):
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:limit]
    try:
        return str(value)[:limit]
    except Exception:
        return "[UNSERIALIZABLE]"


class TervikCallbackHandler:
    """LangChain BaseCallbackHandler-compatible recorder (duck-typed)."""

    def __init__(self, tervik, conversation_id, user_id=None):
        self._tervik = tervik
        self._context = {"conversation_id": conversation_id,
                         **({"user_id": user_id} if user_id else {})}
        self._runs = {}  # run_id -> {trace_id, span_id, started, kind, input}
        self._seen_outputs = set()

    @property
    def _client(self):
        return self._tervik

    def _new_span(self, run_id, kind, inputs, name=None):
        trace_id = self._context.get("trace_id") or str(uuid.uuid4())
        span_id = str(uuid.uuid4())
        self._runs[str(run_id)] = {"trace_id": trace_id, "span_id": span_id,
                                   "started": time.perf_counter(), "kind": kind,
                                   "input": _text(inputs),
                                   "llm_name": _text(name, 200) if name else None}
        return trace_id, span_id

    def _finish(self, run_id, content, status, name, extra=None):
        run = self._runs.pop(str(run_id), None)
        if run is None:
            return  # Unknown or already-recorded run: never duplicate.
        key = (run["trace_id"], run["span_id"], status, content)
        if key in self._seen_outputs:
            return
        self._seen_outputs.add(key)
        metadata = {"input": run["input"], "output": content}
        if extra:
            metadata.update(extra)
        parent = self._context.get("parent_span_id")
        self._client.capture({**self._context, "trace_id": run["trace_id"],
                              "span_id": run["span_id"],
                              **({"parent_span_id": parent} if parent else {}),
                              "role": "assistant" if run["kind"] == "llm" else "tool",
                              "name": name, "status": status, "content": content,
                              "latency_ms": (time.perf_counter() - run["started"]) * 1000,
                              "metadata": metadata})

    # -- LLM events ------------------------------------------------------
    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        name = None
        try:
            if hasattr(serialized, "get"):
                name = serialized.get("name")
        except AttributeError:
            pass
        self._new_span(run_id, "llm", prompts, name=name)

    def on_llm_end(self, response, *, run_id, **kwargs):
        text = ""
        try:
            generations = getattr(response, "generations", None) or []
            first = generations[0][0] if generations and generations[0] else None
            text = getattr(first, "text", "") if first is not None else ""
            message = getattr(first, "message", None)
            if message is not None and getattr(message, "content", None):
                text = message.content if isinstance(message.content, str) else str(message.content)
        except (AttributeError, IndexError, TypeError):
            pass
        name = "langchain.llm"
        run = self._runs.get(str(run_id), {})
        if run.get("llm_name"):
            name = run["llm_name"]
        serialized = kwargs.get("serialized")
        try:
            if hasattr(serialized, "get"):
                name = serialized.get("name", name)
        except AttributeError:
            pass
        self._finish(run_id, _text(text), "success", _text(name, 200) or "langchain.llm")

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._finish(run_id, _text(error), "error", "langchain.llm")

    # -- Tool events -----------------------------------------------------
    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kwargs):
        trace_id, span_id = self._new_span(run_id, "tool", input_str)
        if parent_run_id is not None and str(parent_run_id) in self._runs:
            parent = self._runs[str(parent_run_id)]
            self._runs[str(run_id)]["trace_id"] = parent["trace_id"]
            self._runs[str(run_id)]["parent"] = parent["span_id"]
        name = "langchain.tool"
        try:
            name = serialized.get("name", name) if hasattr(serialized, "get") else name
        except AttributeError:
            pass
        self._runs[str(run_id)]["tool_name"] = _text(name, 200) or "langchain.tool"

    def on_tool_end(self, output, *, run_id, **kwargs):
        run = self._runs.get(str(run_id), {})
        name = run.get("tool_name", "langchain.tool")
        parent = run.pop("parent", None)
        if parent:
            self._context_parent_override = parent
        self._finish_with_parent(run_id, _text(output), "success", name, parent)

    def on_tool_error(self, error, *, run_id, **kwargs):
        run = self._runs.get(str(run_id), {})
        name = run.get("tool_name", "langchain.tool")
        parent = run.pop("parent", None)
        self._finish_with_parent(run_id, _text(error), "error", name, parent)

    def _finish_with_parent(self, run_id, content, status, name, parent):
        run = self._runs.pop(str(run_id), None)
        if run is None:
            return
        key = (run["trace_id"], run["span_id"], status, content)
        if key in self._seen_outputs:
            return
        self._seen_outputs.add(key)
        metadata = {"input": run["input"], "output": content}
        self._client.capture({**self._context, "trace_id": run["trace_id"],
                              "span_id": run["span_id"],
                              **({"parent_span_id": parent} if parent else {}),
                              "role": "tool", "name": name, "status": status,
                              "content": content,
                              "latency_ms": (time.perf_counter() - run["started"]) * 1000,
                              "metadata": metadata})

    # -- Chain events map to turns ---------------------------------------
    def on_chain_start(self, serialized, inputs, *, run_id, **kwargs):
        trace_id, _ = self._new_span(run_id, "chain", inputs)
        self._context = {**self._context, "trace_id": trace_id}
        self._client.capture({**self._context, "trace_id": trace_id,
                              "role": "user", "content": _text(inputs)})

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        self._finish(run_id, _text(outputs), "success", "langchain.chain")

    def on_chain_error(self, error, *, run_id, **kwargs):
        self._finish(run_id, _text(error), "error", "langchain.chain")

    @property
    def run_count(self):
        return len(self._runs)
