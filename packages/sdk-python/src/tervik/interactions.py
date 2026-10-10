"""Interaction tracking: init(), begin()/end(), track(), identify().

One interaction is one agent turn: the user's input and the agent's output,
sent together as a single event to the session/event capture API. Tool calls
made during the turn nest under it with ``interaction.tool()``. Events are
sent from a background thread; nothing here raises into agent code.

    import tervik

    tervik.init("your-project-id")
    turn = tervik.begin(user_id="u-123", agent_name="support", input="Where is my order?")
    with turn.tool("orders.lookup", {"order_id": 42}) as call:
        call.output = lookup(42)
    turn.end(output="It ships tomorrow.")
"""

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .client import CLIENT_NAME, CLIENT_VERSION, _NoRedirect, _error, _scrub, _string, _text

logger = logging.getLogger("tervik")
MAX_TEXT = 32000
MAX_STRING_MAP = 50
RECENT_SESSIONS_PER_USER = 20


def _now_ms():
    return int(time.time() * 1000)


def _clip(value):
    text = value if isinstance(value, str) else ("" if value is None else _string(value))
    return _text(text)[:MAX_TEXT]


def _string_map(values):
    clean = {}
    for key, value in list((values or {}).items())[:MAX_STRING_MAP]:
        if value is None or not str(key).strip():
            continue
        clean[str(key)[:100]] = _clip(value)[:500]
    return _scrub(clean)


class ToolCall:
    """A tool call nested under an interaction (or under another tool call)."""

    def __init__(self, client, parent, name, input_value):
        self._client, self._parent = client, parent
        self.id, self.name, self.input = str(uuid.uuid4()), str(name)[:200] or "tool", input_value
        self.output, self.properties = None, {}
        self._started, self._started_ms, self._ended = time.perf_counter(), _now_ms(), False

    def set_property(self, key, value):
        self.properties[key] = value
        return self

    def set_properties(self, values):
        self.properties.update(values or {})
        return self

    def tool(self, name, input=None):
        return ToolCall(self._client, self, name, input)

    def end(self, output=None, success=True):
        if self._ended:
            return
        self._ended = True
        if output is not None:
            self.output = output
        self._client._event(self._parent.conversation_id, self.id, self.name, self.input, self.output, success,
                            (time.perf_counter() - self._started) * 1000, self._started_ms,
                            self.properties, parent_id=self._parent.id)

    @property
    def conversation_id(self):
        return self._parent.conversation_id

    def __enter__(self):
        return self

    def __exit__(self, kind, error, _):
        if error is not None:
            self.end(output=_error(error), success=False)
        else:
            self.end()
        return False


class Interaction:
    """One agent turn. Call end() once with the agent's output."""

    def __init__(self, client, user_id, agent_name, input_value, conversation_id, interaction_id):
        self._client = client
        self.id = interaction_id or str(uuid.uuid4())
        self.user_id, self.agent_name, self.input = user_id, agent_name, input_value
        self.conversation_id = conversation_id or str(uuid.uuid4())
        self.output, self.properties = None, {}
        self._started, self._started_ms, self._ended = time.perf_counter(), _now_ms(), False

    def set_property(self, key, value):
        self.properties[key] = value
        return self

    def set_properties(self, values):
        self.properties.update(values or {})
        return self

    def tool(self, name, input=None):
        """Start a nested tool call; end it, or use it as a context manager."""
        return ToolCall(self._client, self, name, input)

    def end(self, output=None, success=True, *, latency=None):
        if self._ended:
            return
        self._ended = True
        if output is not None:
            self.output = output
        elapsed = latency if latency is not None else (time.perf_counter() - self._started) * 1000
        self._client._forget(self.id)
        self._client._event(self.conversation_id, self.id, self.agent_name, self.input, self.output, success,
                            elapsed, self._started_ms, self.properties)

    def __enter__(self):
        return self

    def __exit__(self, kind, error, _):
        if error is not None:
            self.end(output=_error(error), success=False)
        else:
            self.end()
        return False


class InteractionClient:
    """Bounded FIFO of capture requests. Sessions precede their events."""

    def __init__(self, project_id=None, *, api_key=None, endpoint=None, debug=False, max_queue_size=1000,
                 flush_interval=1.0, request_timeout=5.0, max_retries=2, retry_base=0.2, redact=None):
        self._project_id = project_id or os.getenv("TERVIK_PROJECT_ID", "")
        self._api_key = api_key if api_key is not None else os.getenv("TERVIK_API_KEY", "")
        self._base = (endpoint or os.getenv("TERVIK_ENDPOINT", "http://127.0.0.1:8000")).rstrip("/")
        parsed = urllib.parse.urlparse(self._base)
        valid = parsed.scheme in ("http", "https") and parsed.hostname and not (parsed.username or parsed.password)
        self.disabled = None if valid and (self._project_id or self._api_key) else "configuration"
        if self.disabled:
            logger.warning("Tervik interactions are disabled: set a project ID (or API key) and an http(s) endpoint")
        self._debug, self._redact = debug, redact
        self._opener = urllib.request.build_opener(_NoRedirect)
        self._timeout, self._retries, self._retry_base = max(0.01, request_timeout), min(10, max(0, max_retries)), max(0, retry_base)
        self._max_queue = max(1, max_queue_size)
        self._lock, self._flush_lock = threading.RLock(), threading.Lock()
        self._queue, self._open, self._traits = [], {}, {}
        self._sessions, self._user_sessions = {}, {}
        self.sent, self.dropped = 0, 0
        self._closed, self._stop, self._worker = False, threading.Event(), None
        if not self.disabled and flush_interval > 0:
            self._worker = threading.Thread(target=self._run, args=(flush_interval,), daemon=True, name="tervik-interactions")
            self._worker.start()

    # ---- public API ----

    def begin(self, user_id, agent_name="agent", input=None, conversation_id=None, interaction_id=None):
        interaction = Interaction(self, str(user_id), str(agent_name)[:200] or "agent", input,
                                  conversation_id, interaction_id)
        with self._lock:
            if interaction_id:
                self._open[interaction_id] = interaction
            # Start the session before any of its events, including tool calls
            # that finish (and send) before the turn does.
            if self._sessions.get(interaction.conversation_id) != interaction.user_id:
                self._sessions[interaction.conversation_id] = interaction.user_id
                recent = self._user_sessions.setdefault(interaction.user_id, [])
                recent.append(interaction.conversation_id)
                del recent[:-RECENT_SESSIONS_PER_USER]
                self._enqueue_session(interaction.conversation_id, interaction.user_id)
        return interaction

    def track(self, user_id, input=None, output=None, agent_name="agent", conversation_id=None, success=True,
              latency=None, properties=None):
        interaction = self.begin(user_id, agent_name, input, conversation_id)
        interaction.set_properties(properties or {})
        interaction.end(output=output, success=success, latency=latency)
        return interaction.id

    def identify(self, user_id, traits=None):
        """Attach traits to a user; they ride along with the user's sessions."""
        user_id = str(user_id)
        with self._lock:
            self._traits[user_id] = {**self._traits.get(user_id, {}), **_string_map(traits)}
            for conversation_id in self._user_sessions.get(user_id, []):
                self._enqueue_session(conversation_id, user_id)

    def get_interaction(self, interaction_id):
        with self._lock:
            return self._open.get(interaction_id)

    def flush(self):
        """Send everything queued now. Blocking; bounded by retries and timeouts."""
        with self._flush_lock:
            while True:
                with self._lock:
                    if not self._queue:
                        return {"sent": self.sent, "dropped": self.dropped, "pending": 0}
                    path, body = self._queue[0]
                if self.disabled:
                    with self._lock:
                        self._drop(len(self._queue))
                        self._queue.clear()
                    continue
                self._send(path, body)
                with self._lock:
                    if self._queue and self._queue[0][1] is body:
                        self._queue.pop(0)

    def shutdown(self):
        self._stop.set()
        with self._lock:
            self._closed = True
        if self._worker and self._worker is not threading.current_thread():
            self._worker.join()
        return self.flush()

    # ---- internals ----

    def _run(self, interval):
        while not self._stop.wait(interval):
            try:
                self.flush()
            except Exception:
                pass

    def _forget(self, interaction_id):
        with self._lock:
            self._open.pop(interaction_id, None)

    def _drop(self, count=1):
        self.dropped += count
        logger.debug("Dropped %s Tervik capture request(s)", count)

    def _push(self, path, body):
        with self._lock:
            if self._closed or self.disabled:
                self._drop()
                return
            if len(self._queue) >= self._max_queue:
                self._drop()
                return
            self._queue.append((path, body))

    def _enqueue_session(self, conversation_id, user_id):
        user_data = {**self._traits.get(user_id, {}), "user_id": user_id[:200]}
        self._push("/api/v1/capture-session", {"session_id": conversation_id, "user_data": user_data,
                                               "client_config": f"{CLIENT_NAME}/{CLIENT_VERSION}"})

    def _event(self, conversation_id, event_id, name, input_value, output, success, latency, started_ms,
               properties, parent_id=None):
        try:
            body = {"event_id": event_id, "session_id": conversation_id, "primitive_name": name,
                    "args": _clip(input_value), "result": _clip(output), "success": bool(success),
                    "latency": max(0.0, round(float(latency), 3)), "timestamp": started_ms,
                    "metadata": _string_map(properties)}
            if parent_id:
                body["parent_id"] = parent_id
            if self._redact:
                body = self._redact(body)
                if body is None:
                    self._drop()
                    return
            self._push("/api/v1/capture-event", body)
        except Exception:
            self._drop()

    def _send(self, path, body):
        data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "X-Tervik-Client": f"{CLIENT_NAME}/{CLIENT_VERSION}"}
        if self._api_key:
            headers["Authorization"] = "Bearer " + self._api_key
        else:
            headers["x-org-id"] = self._project_id
        for attempt in range(self._retries + 1):
            delay = min(2.0, self._retry_base * 2 ** attempt)
            request = urllib.request.Request(self._base + path, data=data, headers=headers, method="POST")
            try:
                with self._opener.open(request, timeout=self._timeout) as response:
                    response.read()
                with self._lock:
                    self.sent += 1
                if self._debug:
                    logger.debug("Tervik %s accepted", path)
                return
            except urllib.error.HTTPError as error:
                status = error.code
                error.close()
                if status in (401, 403):
                    self.disabled = "authentication"
                    logger.warning("Tervik rejected the project ID or API key; capture is disabled")
                    self._drop()
                    return
                if status != 429 and status < 500:
                    logger.debug("Tervik rejected a capture request with HTTP %s", status)
                    self._drop()
                    return
            except Exception:
                pass
            if attempt < self._retries and delay > 0:
                time.sleep(delay)
        self._drop()


_default = None
_default_lock = threading.Lock()


def init(project_id=None, *, api_key=None, endpoint=None, debug=False, **options):
    """Configure the module-level client. Call once, before tracking."""
    global _default
    with _default_lock:
        if _default is not None:
            _default.shutdown()
        _default = InteractionClient(project_id, api_key=api_key, endpoint=endpoint, debug=debug, **options)
        return _default


def _client():
    if _default is None:
        logger.warning("tervik.init() has not been called; capture is disabled")
        return init()
    return _default


def begin(user_id, agent_name="agent", input=None, conversation_id=None, interaction_id=None):
    return _client().begin(user_id, agent_name, input, conversation_id, interaction_id)


def track(user_id, input=None, output=None, agent_name="agent", conversation_id=None, success=True,
          latency=None, properties=None):
    return _client().track(user_id, input, output, agent_name, conversation_id, success, latency, properties)


def identify(user_id, traits=None):
    _client().identify(user_id, traits)


def get_interaction(interaction_id):
    return _client().get_interaction(interaction_id)


def flush():
    return _client().flush() if _default is not None else {"sent": 0, "dropped": 0, "pending": 0}


def shutdown():
    global _default
    with _default_lock:
        result = _default.shutdown() if _default is not None else {"sent": 0, "dropped": 0, "pending": 0}
        _default = None
        return result
