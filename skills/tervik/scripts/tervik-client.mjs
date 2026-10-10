import { randomUUID } from 'node:crypto';
export const SDK_VERSION = '0.1.0';
export const SDK_NAME = '@tervik/sdk';
const SECRET_FIELD = /^(authorization|proxy-authorization|cookie|set-cookie|password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|private[_-]?key)$/i;
function redactText(value) {
    return value
        .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, 'Bearer [REDACTED]')
        .replace(/\bsk-[A-Za-z0-9_-]{12,}/g, '[REDACTED]')
        .replace(/((?:api[_-]?key|password|secret|access[_-]?token)\s*[=:]\s*["']?)[^\s,"'}]+/gi, '$1[REDACTED]');
}
function scrub(value, seen = new WeakSet(), depth = 0) {
    if (value === undefined)
        return undefined;
    if (typeof value === 'string')
        return redactText(value);
    if (value === null || typeof value === 'number' || typeof value === 'boolean')
        return value;
    if (typeof value !== 'object')
        return String(value);
    if (depth > 12)
        return '[MAX DEPTH]';
    if (seen.has(value))
        return '[CIRCULAR]';
    seen.add(value);
    if (Array.isArray(value))
        return value.map(item => scrub(item, seen, depth + 1));
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, SECRET_FIELD.test(key) ? '[REDACTED]' : scrub(item, seen, depth + 1)]));
}
/** Best-effort common-secret filtering. Add a domain redactor for PII and application secrets. */
export function defaultRedact(event) { return scrub(event); }
function stringify(value) {
    if (typeof value === 'string')
        return value;
    try {
        return JSON.stringify(scrub(value)) ?? '';
    }
    catch {
        return '[UNSERIALIZABLE]';
    }
}
function errorText(error) {
    try {
        return error instanceof Error ? error.message : stringify(error);
    }
    catch {
        return '[ERROR MESSAGE UNAVAILABLE]';
    }
}
function positive(value, fallback, min = 1, max = Number.MAX_SAFE_INTEGER) {
    return value === undefined || !Number.isFinite(value) ? fallback : Math.max(min, Math.min(max, Math.floor(value)));
}
const EVENT_FIELDS = new Set(['id', 'conversation_id', 'user_id', 'role', 'content', 'timestamp', 'trace_id', 'span_id', 'parent_span_id', 'name', 'status', 'latency_ms', 'tokens', 'cost_usd', 'model', 'metadata']);
function finiteJson(value) {
    if (typeof value === 'number')
        return Number.isFinite(value);
    if (Array.isArray(value))
        return value.every(finiteJson);
    if (value !== null && typeof value === 'object')
        return Object.values(value).every(finiteJson);
    return true;
}
/** An in-memory, bounded, server-side exporter. Telemetry failures never throw from capture or wrappers. */
export class Tervik {
    apiKey;
    url;
    options;
    queue = [];
    queueBytes = 0;
    inFlightCount = 0;
    inFlightBytes = 0;
    timer;
    flushing;
    disabled;
    closed = false;
    dropped = 0;
    accepted = 0;
    duplicates = 0;
    drops = {};
    constructor(options = {}) {
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
            if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.search || base.hash)
                throw new Error('invalid endpoint');
            base.pathname = base.pathname.replace(/\/$/, '') + '/v1/events';
            this.url = base.toString();
            if (!this.apiKey.trim())
                throw new Error('missing key');
        }
        catch {
            this.disabled = 'configuration';
            this.diagnostic('configuration', 'Tervik disabled: configure a project API key and a valid base endpoint.');
        }
        if (!this.disabled && this.options.flushIntervalMs > 0) {
            this.timer = setInterval(() => { void this.flush(); }, this.options.flushIntervalMs);
            this.timer.unref?.();
        }
    }
    diagnostic(code, message) {
        try {
            if (this.options.onDiagnostic)
                this.options.onDiagnostic({ code, message });
            else
                console.warn(`[Tervik] ${message}`);
        }
        catch { /* Observability callbacks must not affect the customer application. */ }
    }
    drop(reason, count = 1) {
        this.dropped += count;
        this.drops[reason] = (this.drops[reason] ?? 0) + count;
        try {
            if (this.options.onDrop)
                this.options.onDrop({ reason, count });
            else
                this.diagnostic(reason, `Dropped ${count} telemetry event(s): ${reason}.`);
        }
        catch { /* Keep telemetry callbacks isolated. */ }
    }
    /** Queue one real event. Returns its stable ID or null when dropped; makes no network call. */
    capture(event) {
        if (this.closed) {
            this.drop('closed');
            return null;
        }
        if (this.disabled) {
            this.drop(this.disabled);
            return null;
        }
        try {
            let clean = defaultRedact({ ...event, id: event.id ?? randomUUID(), timestamp: event.timestamp ?? new Date().toISOString() });
            if (this.options.redact) {
                const transformed = this.options.redact(clean);
                if (!transformed) {
                    this.drop('redaction');
                    return null;
                }
                clean = defaultRedact(transformed);
            }
            if (!this.valid(clean)) {
                this.drop('invalid_event');
                return null;
            }
            const encoded = JSON.stringify(clean);
            const bytes = Buffer.byteLength(encoded);
            if (bytes + 14 > this.options.maxBatchBytes) {
                this.drop('invalid_event');
                return null;
            }
            if (this.queue.length + this.inFlightCount >= this.options.maxQueueSize || this.queueBytes + this.inFlightBytes + bytes > this.options.maxQueueBytes) {
                this.drop('queue_full');
                return null;
            }
            // JSON round-trip freezes the captured snapshot and removes undefined values.
            this.queue.push({ event: JSON.parse(encoded), bytes });
            this.queueBytes += bytes;
            return clean.id ?? null;
        }
        catch {
            this.drop('redaction');
            return null;
        }
    }
    valid(event) {
        if (!event || Object.keys(event).some(key => !EVENT_FIELDS.has(key)))
            return false;
        if (typeof event.id !== 'string' || !event.id.trim() || event.id.length > 200 || typeof event.conversation_id !== 'string' || !event.conversation_id.trim() || event.conversation_id.length > 200)
            return false;
        if (!['user', 'assistant', 'tool', 'system'].includes(event.role) || typeof event.content !== 'string' || event.content.length > 32000)
            return false;
        if (event.status !== undefined && !['success', 'error'].includes(event.status))
            return false;
        for (const key of ['latency_ms', 'tokens', 'cost_usd']) {
            const value = event[key];
            if (value !== undefined && (typeof value !== 'number' || !Number.isFinite(value) || value < 0))
                return false;
        }
        if (event.tokens !== undefined && !Number.isSafeInteger(event.tokens))
            return false;
        for (const key of ['user_id', 'trace_id', 'span_id', 'parent_span_id', 'name', 'model'])
            if (event[key] !== undefined && (typeof event[key] !== 'string' || event[key].length > 200))
                return false;
        if (event.metadata !== undefined && (!event.metadata || typeof event.metadata !== 'object' || Array.isArray(event.metadata) || !finiteJson(event.metadata)))
            return false;
        return typeof event.timestamp === 'string' && /(?:Z|[+-]\d{2}:?\d{2})$/i.test(event.timestamp) && Number.isFinite(Date.parse(event.timestamp)) && Date.parse(event.timestamp) <= Date.now() + 5 * 60 * 1000;
    }
    /** Drain the events queued at invocation. Concurrent callers share the same drain. */
    flush() {
        if (this.flushing)
            return this.flushing;
        this.flushing = this.drain().finally(() => { this.flushing = undefined; });
        return this.flushing;
    }
    async drain() {
        const before = { accepted: this.accepted, duplicates: this.duplicates, dropped: this.dropped };
        let remaining = this.queue.length;
        while (remaining > 0 && this.queue.length > 0) {
            const batch = [];
            let bytes = 13;
            while (batch.length < this.options.maxBatchSize && batch.length < remaining && this.queue.length > 0) {
                const next = this.queue[0];
                if (batch.length > 0 && bytes + next.bytes + 1 > this.options.maxBatchBytes)
                    break;
                batch.push(this.queue.shift());
                this.queueBytes -= next.bytes;
                bytes += next.bytes + 1;
            }
            remaining -= batch.length;
            this.inFlightCount = batch.length;
            this.inFlightBytes = bytes;
            try {
                await this.send(batch.map(item => item.event));
            }
            finally {
                this.inFlightCount = 0;
                this.inFlightBytes = 0;
            }
            if (this.disabled === 'authentication') {
                if (this.queue.length > 0)
                    this.drop('authentication', this.queue.length);
                this.queue = [];
                this.queueBytes = 0;
                break;
            }
        }
        return { accepted: this.accepted - before.accepted, duplicates: this.duplicates - before.duplicates, dropped: this.dropped - before.dropped, pending: this.queue.length };
    }
    async send(events) {
        const body = JSON.stringify({ events });
        for (let attempt = 0; attempt <= this.options.maxRetries; attempt++) {
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), this.options.requestTimeoutMs);
            let retryAfter = 0;
            try {
                const response = await fetch(this.url, { method: 'POST', headers: { authorization: `Bearer ${this.apiKey}`, 'content-type': 'application/json', 'x-tervik-client': `${SDK_NAME}/${SDK_VERSION}` }, body, signal: controller.signal, redirect: 'error' });
                if (response.status === 401 || response.status === 403) {
                    await response.body?.cancel();
                    this.disabled = 'authentication';
                    this.drop('authentication', events.length);
                    this.diagnostic('authentication', 'Tervik disabled after authentication failure. Check the project key and recreate the client.');
                    return;
                }
                if (response.ok) {
                    const result = await response.json();
                    if (!Number.isInteger(result.accepted) || !Number.isInteger(result.duplicates) || result.accepted < 0 || result.duplicates < 0 || result.accepted + result.duplicates !== events.length)
                        throw new Error('invalid acknowledgement');
                    this.accepted += result.accepted;
                    this.duplicates += result.duplicates;
                    return;
                }
                if (response.status !== 429 && response.status < 500) {
                    await response.body?.cancel();
                    this.drop('server_rejected', events.length);
                    this.diagnostic('server_rejected', `Tervik rejected a batch with HTTP ${response.status}.`);
                    return;
                }
                const header = response.headers.get('retry-after');
                if (header) {
                    const seconds = Number(header);
                    retryAfter = Number.isFinite(seconds) ? seconds * 1000 : Math.max(0, Date.parse(header) - Date.now());
                }
                await response.body?.cancel();
            }
            catch { /* Retry network errors, timeouts and malformed acknowledgements using unchanged IDs. */ }
            finally {
                clearTimeout(timeout);
            }
            if (attempt < this.options.maxRetries) {
                const backoff = this.options.retryBaseMs * 2 ** attempt * (0.8 + Math.random() * 0.4);
                const delay = Math.min(this.options.maxRetryDelayMs, Math.max(backoff, Number.isFinite(retryAfter) ? retryAfter : 0));
                if (delay > 0)
                    await new Promise(resolve => setTimeout(resolve, delay));
            }
        }
        this.drop('retry_exhausted', events.length);
    }
    /** Await on your existing shutdown path; does not install process handlers. */
    async shutdown() {
        if (this.timer)
            clearInterval(this.timer);
        this.closed = true;
        if (this.flushing)
            await this.flushing;
        return this.flush();
    }
    inspect() {
        return { queued: this.queue.length, inFlight: this.inFlightCount, accepted: this.accepted, duplicates: this.duplicates, dropped: this.dropped, drops: { ...this.drops }, disabled: Boolean(this.disabled), closed: this.closed };
    }
    /** Wrap an actual handler. The callback's result and thrown error are preserved. */
    async withTurn(context, input, operation, options = {}) {
        const trace_id = context.trace_id ?? randomUUID();
        const span_id = randomUUID();
        const trace = { ...context, trace_id, parent_span_id: span_id };
        this.capture({ conversation_id: context.conversation_id, user_id: context.user_id, trace_id, role: 'user', content: input });
        const started = performance.now();
        let result;
        try {
            result = await operation(trace);
        }
        catch (error) {
            this.capture({ ...context, trace_id, span_id, role: 'assistant', name: options.name ?? 'agent.turn', model: options.model, status: 'error', content: errorText(error), latency_ms: performance.now() - started, metadata: { input, output: errorText(error) } });
            throw error;
        }
        let output;
        try {
            output = options.output ? options.output(result) : stringify(result);
        }
        catch {
            output = '[OUTPUT MAPPING FAILED]';
            this.diagnostic('output_mapping', 'A telemetry output mapper failed; the agent result was preserved.');
        }
        this.capture({ ...context, trace_id, span_id, role: 'assistant', name: options.name ?? 'agent.turn', model: options.model, status: 'success', content: output, latency_ms: performance.now() - started, metadata: { input, output } });
        return result;
    }
    async withTool(context, name, input, operation) {
        const trace_id = context.trace_id ?? randomUUID();
        const span_id = randomUUID();
        const started = performance.now();
        let result;
        try {
            result = await operation();
        }
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
    async *withStream(context, input, stream, options = {}) {
        const trace_id = context.trace_id ?? randomUUID();
        const span_id = randomUUID();
        const trace = { ...context, trace_id, parent_span_id: span_id };
        this.capture({ conversation_id: context.conversation_id, user_id: context.user_id, trace_id, role: 'user', content: input });
        const started = performance.now();
        const textOf = options.textOf ?? ((chunk) => typeof chunk === 'string' ? chunk : stringify(chunk));
        let full = '';
        let finished = false;
        let failure;
        let hasFailure = false;
        try {
            for await (const chunk of stream) {
                try {
                    full += textOf(chunk);
                }
                catch { /* A text mapper failure must not break the stream. */ }
                yield chunk;
            }
            finished = true;
        }
        catch (error) {
            hasFailure = true;
            failure = error;
        }
        finally {
            // finally: consumer break skips everything after the loop, so the
            // outcome event is recorded here. capture() never throws.
            if (hasFailure) {
                this.capture({ ...context, trace_id, span_id, role: 'assistant', name: options.name ?? 'agent.turn', model: options.model, status: 'error', content: errorText(failure), latency_ms: performance.now() - started, metadata: { input, output: errorText(failure), stream_partial: full } });
            }
            else {
                let output = full;
                try {
                    output = options.output ? options.output(full) : full;
                }
                catch {
                    output = '[OUTPUT MAPPING FAILED]';
                    this.diagnostic('output_mapping', 'A telemetry output mapper failed; the agent result was preserved.');
                }
                this.capture({ ...context, trace_id, span_id, role: 'assistant', name: options.name ?? 'agent.turn', model: options.model, status: 'success', content: output, latency_ms: performance.now() - started, metadata: { input, output, ...(finished ? {} : { stream_cancelled: true }) } });
            }
        }
        if (hasFailure)
            throw failure;
    }
}
const MAX_TEXT = 32000;
function clip(value) {
    const text = value === undefined || value === null ? '' : stringify(value);
    return redactText(text).slice(0, MAX_TEXT);
}
function stringMap(values) {
    const clean = {};
    for (const [key, value] of Object.entries(values ?? {}).slice(0, 50)) {
        if (value === undefined || value === null || !key.trim())
            continue;
        clean[key.slice(0, 100)] = SECRET_FIELD.test(key) ? '[REDACTED]' : clip(value).slice(0, 500);
    }
    return clean;
}
class Operation {
    client;
    id;
    output;
    properties = {};
    startedAt = Date.now();
    started = performance.now();
    ended = false;
    constructor(client, id) {
        this.client = client;
        this.id = id || randomUUID();
    }
    setProperty(key, value) { this.properties[key] = value; return this; }
    setProperties(values) { Object.assign(this.properties, values); return this; }
    /** Start a nested tool call. End it, or pass a function to `run`. */
    tool(name, input) { return new ToolCall(this.client, this, name, input); }
}
export class ToolCall extends Operation {
    parent;
    name;
    input;
    constructor(client, parent, name, input) {
        super(client);
        this.parent = parent;
        this.name = name;
        this.input = input;
    }
    get conversationId() { return this.parent.conversationId; }
    end(output, success = true) {
        if (this.ended)
            return;
        this.ended = true;
        if (output !== undefined)
            this.output = output;
        this.client.event(this.conversationId, this.id, this.name, this.input, this.output, success, performance.now() - this.started, this.startedAt, this.properties, this.parent.id);
    }
    /** Run the tool, record its result or error, and return or rethrow it unchanged. */
    async run(operation) {
        try {
            const result = await operation();
            this.end(result);
            return result;
        }
        catch (error) {
            this.end(errorText(error), false);
            throw error;
        }
    }
}
export class Interaction extends Operation {
    userId;
    agentName;
    input;
    conversationId;
    constructor(client, userId, agentName, input, conversationId, interactionId) {
        super(client, interactionId);
        this.userId = userId;
        this.agentName = agentName;
        this.input = input;
        this.conversationId = conversationId || randomUUID();
    }
    end(output, success = true, latencyMs) {
        if (this.ended)
            return;
        this.ended = true;
        if (output !== undefined)
            this.output = output;
        this.client.forget(this.id);
        this.client.event(this.conversationId, this.id, this.agentName, this.input, this.output, success, latencyMs ?? performance.now() - this.started, this.startedAt, this.properties);
    }
}
/** Bounded FIFO of capture requests. A session is queued before its events. */
export class InteractionClient {
    projectId;
    options;
    disabled;
    base;
    queue = [];
    open = new Map();
    sessions = new Map();
    userSessions = new Map();
    traits = new Map();
    timer;
    flushing;
    closed = false;
    sent = 0;
    dropped = 0;
    constructor(projectId = '', options = {}) {
        this.projectId = projectId;
        this.options = options;
        this.base = (options.endpoint ?? 'http://127.0.0.1:8000').replace(/\/+$/, '');
        let valid = false;
        try {
            const url = new URL(this.base);
            valid = (url.protocol === 'http:' || url.protocol === 'https:') && !url.username && !url.password;
        }
        catch {
            valid = false;
        }
        if (!valid || !(projectId || options.apiKey)) {
            this.disabled = 'configuration';
            console.warn('Tervik interactions are disabled: set a project ID (or API key) and an http(s) endpoint');
        }
        const interval = options.flushIntervalMs ?? 1000;
        if (!this.disabled && interval > 0) {
            this.timer = setInterval(() => { void this.flush(); }, interval);
            this.timer.unref?.();
        }
    }
    begin({ userId, agentName = 'agent', input, conversationId, interactionId }) {
        const interaction = new Interaction(this, String(userId), String(agentName).slice(0, 200) || 'agent', input, conversationId, interactionId);
        if (interactionId)
            this.open.set(interactionId, interaction);
        // Start the session before any of its events, including tool calls that finish first.
        if (this.sessions.get(interaction.conversationId) !== interaction.userId) {
            this.sessions.set(interaction.conversationId, interaction.userId);
            const recent = this.userSessions.get(interaction.userId) ?? [];
            recent.push(interaction.conversationId);
            this.userSessions.set(interaction.userId, recent.slice(-20));
            this.queueSession(interaction.conversationId, interaction.userId);
        }
        return interaction;
    }
    track({ userId, input, output, agentName, conversationId, success = true, latencyMs, properties }) {
        const interaction = this.begin({ userId, agentName, input, conversationId });
        interaction.setProperties(properties ?? {});
        interaction.end(output, success, latencyMs);
        return interaction.id;
    }
    /** Attach traits to a user; they are sent with the user's sessions. */
    identify(userId, traits = {}) {
        const key = String(userId);
        this.traits.set(key, { ...this.traits.get(key), ...stringMap(traits) });
        for (const conversationId of this.userSessions.get(key) ?? [])
            this.queueSession(conversationId, key);
    }
    getInteraction(interactionId) { return this.open.get(interactionId); }
    /** @internal */
    forget(interactionId) { this.open.delete(interactionId); }
    /** @internal */
    event(conversationId, eventId, name, input, output, success, latencyMs, startedAt, properties, parentId) {
        try {
            let body = {
                event_id: eventId, session_id: conversationId, primitive_name: name.slice(0, 200) || 'tool',
                args: clip(input), result: clip(output), success: Boolean(success),
                latency: Math.max(0, Math.round(latencyMs * 1000) / 1000), timestamp: startedAt, metadata: stringMap(properties),
            };
            if (parentId)
                body.parent_id = parentId;
            if (this.options.redact)
                body = this.options.redact(body);
            if (body)
                this.push('/api/v1/capture-event', body);
            else
                this.drop();
        }
        catch {
            this.drop();
        }
    }
    flush() {
        this.flushing ??= this.drain().finally(() => { this.flushing = undefined; });
        return this.flushing;
    }
    async shutdown() {
        this.closed = true;
        if (this.timer)
            clearInterval(this.timer);
        await this.flushing;
        return this.flush();
    }
    async drain() {
        while (this.queue.length) {
            if (this.disabled) {
                this.drop(this.queue.length);
                this.queue.length = 0;
                break;
            }
            const next = this.queue[0];
            await this.send(next.path, next.body);
            if (this.queue[0] === next)
                this.queue.shift();
        }
        return { sent: this.sent, dropped: this.dropped, pending: this.queue.length };
    }
    queueSession(conversationId, userId) {
        this.push('/api/v1/capture-session', {
            session_id: conversationId, user_data: { ...this.traits.get(userId), user_id: userId.slice(0, 200) },
            client_config: `${SDK_NAME}/${SDK_VERSION}`,
        });
    }
    push(path, body) {
        if (this.closed || this.disabled || this.queue.length >= (this.options.maxQueueSize ?? 1000)) {
            this.drop();
            return;
        }
        this.queue.push({ path, body });
    }
    drop(count = 1) {
        this.dropped += count;
        if (this.options.debug)
            console.debug(`Tervik dropped ${count} capture request(s)`);
    }
    async send(path, body) {
        const headers = { 'content-type': 'application/json', 'x-tervik-client': `${SDK_NAME}/${SDK_VERSION}` };
        if (this.options.apiKey)
            headers.authorization = `Bearer ${this.options.apiKey}`;
        else
            headers['x-org-id'] = this.projectId;
        const retries = Math.min(10, Math.max(0, this.options.maxRetries ?? 2));
        for (let attempt = 0; attempt <= retries; attempt++) {
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), this.options.requestTimeoutMs ?? 5000);
            try {
                const response = await fetch(this.base + path, { method: 'POST', headers, body: JSON.stringify(body), signal: controller.signal, redirect: 'error' });
                if (response.ok) {
                    this.sent++;
                    return;
                }
                if (response.status === 401 || response.status === 403) {
                    this.disabled = 'authentication';
                    console.warn('Tervik rejected the project ID or API key; capture is disabled');
                    this.drop();
                    return;
                }
                if (response.status !== 429 && response.status < 500) {
                    this.drop();
                    return;
                }
            }
            catch {
                // Network failure: retry below.
            }
            finally {
                clearTimeout(timeout);
            }
            if (attempt < retries)
                await new Promise(resolve => setTimeout(resolve, Math.min(2000, (this.options.retryBaseMs ?? 200) * 2 ** attempt)));
        }
        this.drop();
    }
}
let defaultClient;
function current() {
    if (!defaultClient) {
        console.warn('tervik.init() has not been called; capture is disabled');
        defaultClient = new InteractionClient();
    }
    return defaultClient;
}
/** Configure the module-level client. Call once, before tracking. */
export function init(projectId, options = {}) {
    void defaultClient?.shutdown();
    defaultClient = new InteractionClient(projectId, options);
    return defaultClient;
}
export function begin(options) { return current().begin(options); }
export function track(options) { return current().track(options); }
export function identify(userId, traits) { current().identify(userId, traits); }
export function getInteraction(interactionId) { return current().getInteraction(interactionId); }
export function flush() { return defaultClient ? defaultClient.flush() : Promise.resolve({ sent: 0, dropped: 0, pending: 0 }); }
export async function shutdown() {
    const client = defaultClient;
    defaultClient = undefined;
    return client ? client.shutdown() : { sent: 0, dropped: 0, pending: 0 };
}
