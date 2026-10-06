import { randomUUID } from 'node:crypto';

export type Role = 'user' | 'assistant' | 'tool' | 'system';
export type DropReason = 'configuration' | 'authentication' | 'queue_full' | 'invalid_event' | 'redaction' | 'server_rejected' | 'retry_exhausted' | 'closed';
export interface Event {
  id?: string;
  conversation_id: string;
  user_id?: string;
  role: Role;
  content: string;
  timestamp?: string;
  trace_id?: string;
  span_id?: string;
  parent_span_id?: string;
  name?: string;
  status?: 'success' | 'error';
  latency_ms?: number;
  tokens?: number;
  cost_usd?: number;
  model?: string;
  metadata?: Record<string, unknown>;
}
export interface Context {
  conversation_id: string;
  user_id?: string;
  trace_id?: string;
  parent_span_id?: string;
}
export interface TraceContext extends Context { trace_id: string; parent_span_id: string }
export interface FlushResult { accepted: number; duplicates: number; dropped: number; pending: number }
export interface Diagnostic { code: string; message: string }
export interface Options {
  apiKey?: string;
  /** Base origin, e.g. http://127.0.0.1:8000; /v1/events is appended. */
  endpoint?: string;
  maxQueueSize?: number;
  maxQueueBytes?: number;
  maxBatchSize?: number;
  maxBatchBytes?: number;
  flushIntervalMs?: number;
  requestTimeoutMs?: number;
  maxRetries?: number;
  retryBaseMs?: number;
  maxRetryDelayMs?: number;
  /** Runs after built-in redaction, before the event enters memory or leaves the process. */
  redact?: (event: Event) => Event | null;
  onDrop?: (notice: { reason: DropReason; count: number }) => void;
  onDiagnostic?: (notice: Diagnostic) => void;
}

const SECRET_FIELD = /^(authorization|proxy-authorization|cookie|set-cookie|password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|private[_-]?key)$/i;
function redactText(value: string): string {
  return value
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, 'Bearer [REDACTED]')
    .replace(/\bsk-[A-Za-z0-9_-]{12,}/g, '[REDACTED]')
    .replace(/((?:api[_-]?key|password|secret|access[_-]?token)\s*[=:]\s*["']?)[^\s,"'}]+/gi, '$1[REDACTED]');
}
function scrub(value: unknown, seen = new WeakSet<object>(), depth = 0): unknown {
  if (value === undefined) return undefined;
  if (typeof value === 'string') return redactText(value);
  if (value === null || typeof value === 'number' || typeof value === 'boolean') return value;
  if (typeof value !== 'object') return String(value);
  if (depth > 12) return '[MAX DEPTH]';
  if (seen.has(value)) return '[CIRCULAR]';
  seen.add(value);
  if (Array.isArray(value)) return value.map(item => scrub(item, seen, depth + 1));
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, SECRET_FIELD.test(key) ? '[REDACTED]' : scrub(item, seen, depth + 1)]));
}
/** Best-effort common-secret filtering. Add a domain redactor for PII and application secrets. */
export function defaultRedact(event: Event): Event { return scrub(event) as Event; }
function stringify(value: unknown): string {
  if (typeof value === 'string') return value;
  try { return JSON.stringify(scrub(value)) ?? ''; } catch { return '[UNSERIALIZABLE]'; }
}
function errorText(error: unknown): string {
  try { return error instanceof Error ? error.message : stringify(error); }
  catch { return '[ERROR MESSAGE UNAVAILABLE]'; }
}
function positive(value: number | undefined, fallback: number, min = 1, max = Number.MAX_SAFE_INTEGER): number {
  return value === undefined || !Number.isFinite(value) ? fallback : Math.max(min, Math.min(max, Math.floor(value)));
}
type Queued = { event: Event; bytes: number };
const EVENT_FIELDS = new Set(['id', 'conversation_id', 'user_id', 'role', 'content', 'timestamp', 'trace_id', 'span_id', 'parent_span_id', 'name', 'status', 'latency_ms', 'tokens', 'cost_usd', 'model', 'metadata']);
function finiteJson(value: unknown): boolean {
  if (typeof value === 'number') return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(finiteJson);
  if (value !== null && typeof value === 'object') return Object.values(value).every(finiteJson);
  return true;
}

/** An in-memory, bounded, server-side exporter. Telemetry failures never throw from capture or wrappers. */
export class Tervik {
  private readonly apiKey: string;
  private readonly url: string;
  private readonly options: Required<Pick<Options, 'maxQueueSize' | 'maxQueueBytes' | 'maxBatchSize' | 'maxBatchBytes' | 'flushIntervalMs' | 'requestTimeoutMs' | 'maxRetries' | 'retryBaseMs' | 'maxRetryDelayMs'>> & Options;
  private queue: Queued[] = [];
  private queueBytes = 0;
  private inFlightCount = 0;
  private inFlightBytes = 0;
  private timer?: ReturnType<typeof setInterval>;
  private flushing?: Promise<FlushResult>;
  private disabled?: 'configuration' | 'authentication';
  private closed = false;
  private dropped = 0;
  private accepted = 0;
  private duplicates = 0;
  private drops: Partial<Record<DropReason, number>> = {};

  constructor(options: Options = {}) {
    this.options = {
      ...options,
      maxQueueSize: positive(options.maxQueueSize, 1000),
      maxQueueBytes: positive(options.maxQueueBytes, 5 * 1024 * 1024),
      maxBatchSize: positive(options.maxBatchSize, 100, 1, 100),
      maxBatchBytes: positive(options.maxBatchBytes, 256 * 1024, 128),
      flushIntervalMs: positive(options.flushIntervalMs, 1000, 0),
      requestTimeoutMs: positive(options.requestTimeoutMs, 5000),
      maxRetries: positive(options.maxRetries, 2, 0, 10),
      retryBaseMs: positive(options.retryBaseMs, 200, 0),
      maxRetryDelayMs: positive(options.maxRetryDelayMs, 2000, 0)
    };
    this.apiKey = options.apiKey ?? process.env.TERVIK_API_KEY ?? '';
    this.url = '';
    try {
      const base = new URL(options.endpoint ?? process.env.TERVIK_ENDPOINT ?? 'http://127.0.0.1:8000');
      if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.search || base.hash) throw new Error('invalid endpoint');
      base.pathname = base.pathname.replace(/\/$/, '') + '/v1/events';
      this.url = base.toString();
      if (!this.apiKey.trim()) throw new Error('missing key');
    } catch {
      this.disabled = 'configuration';
      this.diagnostic('configuration', 'Tervik disabled: configure a project API key and a valid base endpoint.');
    }
    if (!this.disabled && this.options.flushIntervalMs > 0) {
      this.timer = setInterval(() => { void this.flush(); }, this.options.flushIntervalMs);
      this.timer.unref?.();
    }
  }

  private diagnostic(code: string, message: string): void {
    try {
      if (this.options.onDiagnostic) this.options.onDiagnostic({ code, message });
      else console.warn(`[Tervik] ${message}`);
    } catch { /* Observability callbacks must not affect the customer application. */ }
  }

  private drop(reason: DropReason, count = 1): void {
    this.dropped += count;
    this.drops[reason] = (this.drops[reason] ?? 0) + count;
    try {
      if (this.options.onDrop) this.options.onDrop({ reason, count });
      else this.diagnostic(reason, `Dropped ${count} telemetry event(s): ${reason}.`);
    } catch { /* Keep telemetry callbacks isolated. */ }
  }

  /** Queue one real event. Returns its stable ID or null when dropped; makes no network call. */
  capture(event: Event): string | null {
    if (this.closed) { this.drop('closed'); return null; }
    if (this.disabled) { this.drop(this.disabled); return null; }
    try {
      let clean = defaultRedact({ ...event, id: event.id ?? randomUUID(), timestamp: event.timestamp ?? new Date().toISOString() });
      if (this.options.redact) {
        const transformed = this.options.redact(clean);
        if (!transformed) { this.drop('redaction'); return null; }
        clean = defaultRedact(transformed);
      }
      if (!this.valid(clean)) { this.drop('invalid_event'); return null; }
      const encoded = JSON.stringify(clean);
      const bytes = Buffer.byteLength(encoded);
      if (bytes + 14 > this.options.maxBatchBytes) { this.drop('invalid_event'); return null; }
      if (this.queue.length + this.inFlightCount >= this.options.maxQueueSize || this.queueBytes + this.inFlightBytes + bytes > this.options.maxQueueBytes) {
        this.drop('queue_full'); return null;
      }
      // JSON round-trip freezes the captured snapshot and removes undefined values.
      this.queue.push({ event: JSON.parse(encoded) as Event, bytes });
      this.queueBytes += bytes;
      return clean.id ?? null;
    } catch { this.drop('redaction'); return null; }
  }

  private valid(event: Event): boolean {
    if (!event || Object.keys(event).some(key => !EVENT_FIELDS.has(key))) return false;
    if (typeof event.id !== 'string' || !event.id.trim() || event.id.length > 200 || typeof event.conversation_id !== 'string' || !event.conversation_id.trim() || event.conversation_id.length > 200) return false;
    if (!['user', 'assistant', 'tool', 'system'].includes(event.role) || typeof event.content !== 'string' || event.content.length > 32000) return false;
    if (event.status !== undefined && !['success', 'error'].includes(event.status)) return false;
    for (const key of ['latency_ms', 'tokens', 'cost_usd'] as const) {
      const value = event[key];
      if (value !== undefined && (typeof value !== 'number' || !Number.isFinite(value) || value < 0)) return false;
    }
    if (event.tokens !== undefined && !Number.isSafeInteger(event.tokens)) return false;
    for (const key of ['user_id', 'trace_id', 'span_id', 'parent_span_id', 'name', 'model'] as const) if (event[key] !== undefined && (typeof event[key] !== 'string' || event[key].length > 200)) return false;
    if (event.metadata !== undefined && (!event.metadata || typeof event.metadata !== 'object' || Array.isArray(event.metadata) || !finiteJson(event.metadata))) return false;
    return typeof event.timestamp === 'string' && /(?:Z|[+-]\d{2}:?\d{2})$/i.test(event.timestamp) && Number.isFinite(Date.parse(event.timestamp)) && Date.parse(event.timestamp) <= Date.now() + 5 * 60 * 1000;
  }

  /** Drain the events queued at invocation. Concurrent callers share the same drain. */
  flush(): Promise<FlushResult> {
    if (this.flushing) return this.flushing;
    this.flushing = this.drain().finally(() => { this.flushing = undefined; });
    return this.flushing;
  }

  private async drain(): Promise<FlushResult> {
    const before = { accepted: this.accepted, duplicates: this.duplicates, dropped: this.dropped };
    let remaining = this.queue.length;
    while (remaining > 0 && this.queue.length > 0) {
      const batch: Queued[] = [];
      let bytes = 13;
      while (batch.length < this.options.maxBatchSize && batch.length < remaining && this.queue.length > 0) {
        const next = this.queue[0]!;
        if (batch.length > 0 && bytes + next.bytes + 1 > this.options.maxBatchBytes) break;
        batch.push(this.queue.shift()!);
        this.queueBytes -= next.bytes;
        bytes += next.bytes + 1;
      }
      remaining -= batch.length;
      this.inFlightCount = batch.length;
      this.inFlightBytes = bytes;
      try { await this.send(batch.map(item => item.event)); }
      finally { this.inFlightCount = 0; this.inFlightBytes = 0; }
      if (this.disabled === 'authentication') {
        if (this.queue.length > 0) this.drop('authentication', this.queue.length);
        this.queue = []; this.queueBytes = 0; break;
      }
    }
    return { accepted: this.accepted - before.accepted, duplicates: this.duplicates - before.duplicates, dropped: this.dropped - before.dropped, pending: this.queue.length };
  }

  private async send(events: Event[]): Promise<void> {
    const body = JSON.stringify({ events });
    for (let attempt = 0; attempt <= this.options.maxRetries; attempt++) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), this.options.requestTimeoutMs);
      let retryAfter = 0;
      try {
        const response = await fetch(this.url, { method: 'POST', headers: { authorization: `Bearer ${this.apiKey}`, 'content-type': 'application/json' }, body, signal: controller.signal, redirect: 'error' });
        if (response.status === 401 || response.status === 403) {
          await response.body?.cancel();
          this.disabled = 'authentication'; this.drop('authentication', events.length);
          this.diagnostic('authentication', 'Tervik disabled after authentication failure. Check the project key and recreate the client.');
          return;
        }
        if (response.ok) {
          const result = await response.json() as { accepted: number; duplicates: number };
          if (!Number.isInteger(result.accepted) || !Number.isInteger(result.duplicates) || result.accepted < 0 || result.duplicates < 0 || result.accepted + result.duplicates !== events.length) throw new Error('invalid acknowledgement');
          this.accepted += result.accepted; this.duplicates += result.duplicates; return;
        }
        if (response.status !== 429 && response.status < 500) {
          await response.body?.cancel(); this.drop('server_rejected', events.length);
          this.diagnostic('server_rejected', `Tervik rejected a batch with HTTP ${response.status}.`); return;
        }
        const header = response.headers.get('retry-after');
        if (header) {
          const seconds = Number(header);
          retryAfter = Number.isFinite(seconds) ? seconds * 1000 : Math.max(0, Date.parse(header) - Date.now());
        }
        await response.body?.cancel();
      } catch { /* Retry network errors, timeouts and malformed acknowledgements using unchanged IDs. */ }
      finally { clearTimeout(timeout); }
      if (attempt < this.options.maxRetries) {
        const backoff = this.options.retryBaseMs * 2 ** attempt * (0.8 + Math.random() * 0.4);
        const delay = Math.min(this.options.maxRetryDelayMs, Math.max(backoff, Number.isFinite(retryAfter) ? retryAfter : 0));
        if (delay > 0) await new Promise(resolve => setTimeout(resolve, delay));
      }
    }
    this.drop('retry_exhausted', events.length);
  }

  /** Await on your existing shutdown path; does not install process handlers. */
  async shutdown(): Promise<FlushResult> {
    if (this.timer) clearInterval(this.timer);
    this.closed = true;
    if (this.flushing) await this.flushing;
    return this.flush();
  }

  inspect(): { queued: number; inFlight: number; accepted: number; duplicates: number; dropped: number; drops: Partial<Record<DropReason, number>>; disabled: boolean; closed: boolean } {
    return { queued: this.queue.length, inFlight: this.inFlightCount, accepted: this.accepted, duplicates: this.duplicates, dropped: this.dropped, drops: { ...this.drops }, disabled: Boolean(this.disabled), closed: this.closed };
  }

  /** Wrap an actual handler. The callback's result and thrown error are preserved. */
  async withTurn<T>(context: Context, input: string, operation: (trace: TraceContext) => Promise<T>, options: { name?: string; model?: string; output?: (value: T) => string } = {}): Promise<T> {
    const trace_id = context.trace_id ?? randomUUID();
    const span_id = randomUUID();
    const trace: TraceContext = { ...context, trace_id, parent_span_id: span_id };
    this.capture({ conversation_id: context.conversation_id, user_id: context.user_id, trace_id, role: 'user', content: input });
    const started = performance.now();
    let result: T;
    try { result = await operation(trace); }
    catch (error) {
      this.capture({ ...context, trace_id, span_id, role: 'assistant', name: options.name ?? 'agent.turn', model: options.model, status: 'error', content: errorText(error), latency_ms: performance.now() - started, metadata: { input, output: errorText(error) } });
      throw error;
    }
    let output: string;
    try { output = options.output ? options.output(result) : stringify(result); }
    catch { output = '[OUTPUT MAPPING FAILED]'; this.diagnostic('output_mapping', 'A telemetry output mapper failed; the agent result was preserved.'); }
    this.capture({ ...context, trace_id, span_id, role: 'assistant', name: options.name ?? 'agent.turn', model: options.model, status: 'success', content: output, latency_ms: performance.now() - started, metadata: { input, output } });
    return result;
  }

  async withTool<T>(context: Context, name: string, input: unknown, operation: () => Promise<T>): Promise<T> {    const trace_id = context.trace_id ?? randomUUID();
    const span_id = randomUUID();
    const started = performance.now();
    let result: T;
    try { result = await operation(); }
    catch (error) {
      this.capture({ ...context, trace_id, span_id, role: 'tool', name, status: 'error', content: errorText(error), latency_ms: performance.now() - started, metadata: { input, output: errorText(error) } });
      throw error;
    }
    const output = stringify(result);
    this.capture({ ...context, trace_id, span_id, role: 'tool', name, status: 'success', content: output, latency_ms: performance.now() - started, metadata: { input, output: result } });
    return result;
  }

  /**
   * Wrap an actual streaming operation. The original iterator is preserved:
   * chunks are yielded to the caller untouched while permitted text is
   * accumulated for one assistant event. Early termination records a partial
   * outcome; errors record the actual failure. Telemetry never throws.
   */
  async *withStream<T>(context: Context, input: string, stream: AsyncIterable<T>, options: { name?: string; model?: string; textOf?: (chunk: T) => string; output?: (full: string) => string } = {}): AsyncGenerator<T, void, unknown> {
    const trace_id = context.trace_id ?? randomUUID();
    const span_id = randomUUID();
    const trace: TraceContext = { ...context, trace_id, parent_span_id: span_id };
    this.capture({ conversation_id: context.conversation_id, user_id: context.user_id, trace_id, role: 'user', content: input });
    const started = performance.now();
    const textOf = options.textOf ?? ((chunk: T) => typeof chunk === 'string' ? chunk : stringify(chunk));
    let full = '';
    let finished = false;
    let failure: unknown;
    let hasFailure = false;
    try {
      for await (const chunk of stream) {
        try { full += textOf(chunk); } catch { /* A text mapper failure must not break the stream. */ }
        yield chunk;
      }
      finished = true;
    } catch (error) {
      hasFailure = true;
      failure = error;
    } finally {
      // finally: consumer break skips everything after the loop, so the
      // outcome event is recorded here. capture() never throws.
      if (hasFailure) {
        this.capture({ ...context, trace_id, span_id, role: 'assistant', name: options.name ?? 'agent.turn', model: options.model, status: 'error', content: errorText(failure), latency_ms: performance.now() - started, metadata: { input, output: errorText(failure), stream_partial: full } });
      } else {
        let output = full;
        try { output = options.output ? options.output(full) : full; }
        catch { output = '[OUTPUT MAPPING FAILED]'; this.diagnostic('output_mapping', 'A telemetry output mapper failed; the agent result was preserved.'); }
        this.capture({ ...context, trace_id, span_id, role: 'assistant', name: options.name ?? 'agent.turn', model: options.model, status: 'success', content: output, latency_ms: performance.now() - started, metadata: { input, output, ...(finished ? {} : { stream_cancelled: true }) } });
      }
    }
    if (hasFailure) throw failure;
  }
}
