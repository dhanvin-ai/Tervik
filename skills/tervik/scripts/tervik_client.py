"""Portable server-side Tervik exporter; Python stdlib only, no durable-delivery promise."""

import json
import logging
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

_SECRET_FIELD = re.compile(r"^(authorization|proxy-authorization|cookie|set-cookie|password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|private[_-]?key)$", re.I)
_EVENT_FIELDS = {"id", "conversation_id", "user_id", "role", "content", "timestamp", "trace_id", "span_id", "parent_span_id", "name", "status", "latency_ms", "tokens", "cost_usd", "model", "metadata"}
CLIENT_VERSION = "0.1.0"
CLIENT_NAME = "tervik-python"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def _text(value):
    value = re.sub(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", value, flags=re.I)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}", "[REDACTED]", value)
    return re.sub(r"((?:api[_-]?key|password|secret|access[_-]?token)\s*[=:]\s*[\"']?)[^\s,\"'}]+", r"\1[REDACTED]", value, flags=re.I)


def _scrub(value, seen=None, depth=0):
    if isinstance(value, str):
        return _text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if depth > 12:
        return "[MAX DEPTH]"
    seen = set() if seen is None else seen
    if id(value) in seen:
        return "[CIRCULAR]"
    seen.add(id(value))
    if isinstance(value, (list, tuple)):
        return [_scrub(item, seen, depth + 1) for item in value]
    if isinstance(value, dict):
        return {str(key): "[REDACTED]" if _SECRET_FIELD.match(str(key)) else _scrub(item, seen, depth + 1) for key, item in value.items()}
    return _text(str(value))


def _string(value):
    if isinstance(value, str):
        return value
    try:
        return json.dumps(_scrub(value), ensure_ascii=False, allow_nan=False)
    except Exception:
        return "[UNSERIALIZABLE]"


def _error(error):
    try:
        return str(error)
    except Exception:
        return "[ERROR MESSAGE UNAVAILABLE]"


class Tervik:
    """Queues real events, retries boundedly, and isolates telemetry errors from agent code."""

    def __init__(self, api_key=None, endpoint=None, *, redact=None, on_drop=None,
                 max_queue_size=1000, max_queue_bytes=5 * 1024 * 1024,
                 max_batch_size=100, max_batch_bytes=256 * 1024,
                 flush_interval=1.0, request_timeout=5.0, max_retries=2,
                 retry_base=0.2):
        self._key = api_key if api_key is not None else os.getenv("TERVIK_API_KEY", "")
        self._url = (endpoint or os.getenv("TERVIK_ENDPOINT", "http://127.0.0.1:8000")).rstrip("/") + "/v1/events"
        parsed = urllib.parse.urlparse(self._url)
        self._disabled = None if self._key and parsed.scheme in ("http", "https") and parsed.hostname and not (parsed.username or parsed.password or parsed.query or parsed.fragment) else "configuration"
        self._redact, self._on_drop = redact, on_drop
        self._opener = urllib.request.build_opener(_NoRedirect)
        self._max_queue_size, self._max_queue_bytes = max(1, max_queue_size), max(1, max_queue_bytes)
        self._max_batch_size, self._max_batch_bytes = min(100, max(1, max_batch_size)), max(128, max_batch_bytes)
        self._timeout, self._retries, self._retry_base = max(0.01, request_timeout), min(10, max(0, max_retries)), max(0, retry_base)
        self._lock, self._flush_lock = threading.RLock(), threading.Lock()
        self._queue, self._bytes, self._inflight, self._inflight_bytes = [], 0, 0, 0
        self._accepted, self._duplicates, self._dropped, self._drops = 0, 0, 0, {}
        self._closed, self._stop, self._worker = False, threading.Event(), None
        if not self._disabled and flush_interval > 0:
            self._worker = threading.Thread(target=self._run, args=(flush_interval,), daemon=True, name="tervik-export")
            self._worker.start()

    def _run(self, interval):
        while not self._stop.wait(interval):
            self.flush()

    def _drop(self, reason, count=1):
        with self._lock:
            self._dropped += count
            self._drops[reason] = self._drops.get(reason, 0) + count
        try:
            if self._on_drop:
                self._on_drop({"reason": reason, "count": count})
            else:
                logging.getLogger("tervik").warning("Dropped %s telemetry event(s): %s", count, reason)
        except Exception:
            pass

    def capture(self, event):
        """Return a stable ID or None; no HTTP request occurs on the caller thread."""
        with self._lock:
            if self._closed or self._disabled:
                self._drop("closed" if self._closed else self._disabled)
                return None
        try:
            clean = _scrub(dict(event))
            clean.setdefault("id", str(uuid.uuid4()))
            clean.setdefault("timestamp", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
            if self._redact:
                clean = self._redact(clean)
                if clean is None:
                    self._drop("redaction")
                    return None
                clean = _scrub(clean)
            if not self._valid(clean):
                self._drop("invalid_event")
                return None
            encoded = json.dumps(clean, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            size = len(encoded.encode("utf-8"))
            if size + 14 > self._max_batch_bytes:
                self._drop("invalid_event")
                return None
            with self._lock:
                if self._closed:
                    self._drop("closed")
                    return None
                if len(self._queue) + self._inflight >= self._max_queue_size or self._bytes + self._inflight_bytes + size > self._max_queue_bytes:
                    self._drop("queue_full")
                    return None
                self._queue.append((json.loads(encoded), size))
                self._bytes += size
            return clean["id"]
        except Exception:
            self._drop("redaction")
            return None

    @staticmethod
    def _valid(event):
        if not isinstance(event, dict) or set(event) - _EVENT_FIELDS or not all(isinstance(event.get(key), str) and event[key].strip() and len(event[key]) <= 200 for key in ("id", "conversation_id")):
            return False
        if event.get("role") not in ("user", "assistant", "tool", "system") or not isinstance(event.get("content"), str) or len(event["content"]) > 32000:
            return False
        if event.get("status", "success") not in ("success", "error"):
            return False
        for key in ("latency_ms", "tokens", "cost_usd"):
            if key in event and (isinstance(event[key], bool) or not isinstance(event[key], (int, float)) or not math.isfinite(event[key]) or event[key] < 0):
                return False
        if "tokens" in event and type(event["tokens"]) is not int:
            return False
        for key in ("user_id", "trace_id", "span_id", "parent_span_id", "name", "model"):
            if key in event and event[key] is not None and (not isinstance(event[key], str) or len(event[key]) > 200):
                return False
        if "metadata" in event and not isinstance(event["metadata"], dict):
            return False
        try:
            json.dumps(event.get("metadata", {}), allow_nan=False)
            stamp = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
            return stamp.tzinfo is not None and stamp <= datetime.now(timezone.utc) + timedelta(minutes=5)
        except (ValueError, TypeError, KeyError, AttributeError):
            return False

    def flush(self):
        """Blocking bounded export; use asyncio.to_thread outside an async response path."""
        with self._flush_lock:
            with self._lock:
                before = self._accepted, self._duplicates, self._dropped
                remaining = len(self._queue)
            while remaining > 0:
                with self._lock:
                    batch, size = [], 13
                    while self._queue and len(batch) < min(remaining, self._max_batch_size):
                        event, event_bytes = self._queue[0]
                        if batch and size + event_bytes + 1 > self._max_batch_bytes:
                            break
                        self._queue.pop(0)
                        self._bytes -= event_bytes
                        batch.append(event)
                        size += event_bytes + 1
                    self._inflight, self._inflight_bytes = len(batch), size
                    remaining -= len(batch)
                if not batch:
                    break
                try:
                    self._send(batch)
                finally:
                    with self._lock:
                        self._inflight, self._inflight_bytes = 0, 0
                if self._disabled == "authentication":
                    with self._lock:
                        if self._queue:
                            self._drop("authentication", len(self._queue))
                        self._queue, self._bytes = [], 0
                    break
            with self._lock:
                return {"accepted": self._accepted - before[0], "duplicates": self._duplicates - before[1], "dropped": self._dropped - before[2], "pending": len(self._queue)}

    def _send(self, events):
        body = json.dumps({"events": events}, ensure_ascii=False, allow_nan=False).encode("utf-8")
        for attempt in range(self._retries + 1):
            delay = min(2.0, self._retry_base * 2 ** attempt)
            request = urllib.request.Request(self._url, data=body, headers={"Authorization": "Bearer " + self._key, "Content-Type": "application/json", "X-Tervik-Client": CLIENT_NAME + "/" + CLIENT_VERSION}, method="POST")
            try:
                with self._opener.open(request, timeout=self._timeout) as response:
                    result = json.load(response)
                accepted, duplicates = result.get("accepted"), result.get("duplicates")
                if type(accepted) is not int or type(duplicates) is not int or accepted < 0 or duplicates < 0 or accepted + duplicates != len(events):
                    raise ValueError("invalid acknowledgement")
                with self._lock:
                    self._accepted += accepted
                    self._duplicates += duplicates
                return
            except urllib.error.HTTPError as error:
                status, retry_after = error.code, error.headers.get("Retry-After", "0")
                error.close()
                if status in (401, 403):
                    self._disabled = "authentication"
                    self._drop("authentication", len(events))
                    return
                if status != 429 and status < 500:
                    self._drop("server_rejected", len(events))
                    return
                try:
                    delay = min(2.0, max(delay, float(retry_after)))
                except (TypeError, ValueError):
                    pass
            except Exception:
                pass
            if attempt < self._retries and delay > 0:
                time.sleep(delay)
        self._drop("retry_exhausted", len(events))

    def inspect(self):
        with self._lock:
            return {"queued": len(self._queue), "in_flight": self._inflight, "accepted": self._accepted, "duplicates": self._duplicates, "dropped": self._dropped, "drops": dict(self._drops), "disabled": bool(self._disabled), "closed": self._closed}

    def shutdown(self):
        self._stop.set()
        with self._lock:
            self._closed = True
        if self._worker and self._worker is not threading.current_thread():
            self._worker.join()
        return self.flush()

    @contextmanager
    def span(self, context, role, name, input_value):
        span_id, trace_id, start = str(uuid.uuid4()), context.get("trace_id") or str(uuid.uuid4()), time.perf_counter()
        span = SimpleNamespace(output=None, trace={**context, "trace_id": trace_id, "parent_span_id": span_id})
        status, content = "success", ""
        try:
            yield span
            content = _string(span.output)
        except BaseException as error:
            status, content = "error", _error(error)
            raise
        finally:
            self.capture({**context, "trace_id": trace_id, "span_id": span_id, "role": role, "name": name, "status": status, "content": content, "latency_ms": (time.perf_counter() - start) * 1000, "metadata": {"input": input_value, "output": content}})

    async def with_turn(self, context, input_value, operation, *, output=None, name="agent.turn", model=None):
        trace_id = context.get("trace_id") or str(uuid.uuid4())
        self.capture({**context, "trace_id": trace_id, "role": "user", "content": input_value})
        span_context = {**context, "trace_id": trace_id}
        if model is not None:
            span_context["model"] = model
        with self.span(span_context, "assistant", name, input_value) as span:
            result = await operation(span.trace)
            try:
                span.output = output(result) if output else result
            except Exception:
                span.output = "[OUTPUT MAPPING FAILED]"
            return result

    def stream_turn(self, context, input_value, chunks, *, text_of=None, name="agent.turn", model=None):
        """Wrap an actual sync iterable of chunks. Chunks pass through untouched;
        permitted text is accumulated for one assistant event. Early termination
        records a partial outcome; errors record the failure. Telemetry never throws."""
        trace_id = context.get("trace_id") or str(uuid.uuid4())
        span_id, start = str(uuid.uuid4()), time.perf_counter()
        self.capture({**context, "trace_id": trace_id, "role": "user", "content": input_value})
        full, finished, status = "", False, "success"
        try:
            for chunk in chunks:
                try:
                    text = text_of(chunk) if text_of else (chunk if isinstance(chunk, str) else _string(chunk))
                    full += text
                except Exception:
                    pass
                yield chunk
            finished = True
        except GeneratorExit:
            raise
        except BaseException as error:
            status = "error"
            full = _error(error)
            raise
        finally:
            meta = {"input": input_value, "output": full}
            if finished is False and status == "success":
                meta["stream_cancelled"] = True
            span_context = {**context, "trace_id": trace_id}
            if model is not None:
                span_context["model"] = model
            self.capture({**span_context, "span_id": span_id, "role": "assistant", "name": name,
                          "status": status, "content": full,
                          "latency_ms": (time.perf_counter() - start) * 1000, "metadata": meta})

    async def astream_turn(self, context, input_value, chunks, *, text_of=None, name="agent.turn", model=None):
        """Async-iterable variant of stream_turn. Preserves the original chunks."""
        trace_id = context.get("trace_id") or str(uuid.uuid4())
        span_id, start = str(uuid.uuid4()), time.perf_counter()
        self.capture({**context, "trace_id": trace_id, "role": "user", "content": input_value})
        full, finished, status = "", False, "success"
        try:
            async for chunk in chunks:
                try:
                    text = text_of(chunk) if text_of else (chunk if isinstance(chunk, str) else _string(chunk))
                    full += text
                except Exception:
                    pass
                yield chunk
            finished = True
        except GeneratorExit:
            raise
        except BaseException as error:
            status = "error"
            full = _error(error)
            raise
        finally:
            meta = {"input": input_value, "output": full}
            if finished is False and status == "success":
                meta["stream_cancelled"] = True
            span_context = {**context, "trace_id": trace_id}
            if model is not None:
                span_context["model"] = model
            self.capture({**span_context, "span_id": span_id, "role": "assistant", "name": name,
                          "status": status, "content": full,
                          "latency_ms": (time.perf_counter() - start) * 1000, "metadata": meta})
