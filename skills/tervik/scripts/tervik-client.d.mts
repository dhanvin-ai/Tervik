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
export interface TraceContext extends Context {
    trace_id: string;
    parent_span_id: string;
}
export interface FlushResult {
    accepted: number;
    duplicates: number;
    dropped: number;
    pending: number;
}
export interface Diagnostic {
    code: string;
    message: string;
}
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
    onDrop?: (notice: {
        reason: DropReason;
        count: number;
    }) => void;
    onDiagnostic?: (notice: Diagnostic) => void;
}
/** Best-effort common-secret filtering. Add a domain redactor for PII and application secrets. */
export declare function defaultRedact(event: Event): Event;
/** An in-memory, bounded, server-side exporter. Telemetry failures never throw from capture or wrappers. */
export declare class Tervik {
    private readonly apiKey;
    private readonly url;
    private readonly options;
    private queue;
    private queueBytes;
    private inFlightCount;
    private inFlightBytes;
    private timer?;
    private flushing?;
    private disabled?;
    private closed;
    private dropped;
    private accepted;
    private duplicates;
    private drops;
    constructor(options?: Options);
    private diagnostic;
    private drop;
    /** Queue one real event. Returns its stable ID or null when dropped; makes no network call. */
    capture(event: Event): string | null;
    private valid;
    /** Drain the events queued at invocation. Concurrent callers share the same drain. */
    flush(): Promise<FlushResult>;
    private drain;
    private send;
    /** Await on your existing shutdown path; does not install process handlers. */
    shutdown(): Promise<FlushResult>;
    inspect(): {
        queued: number;
        inFlight: number;
        accepted: number;
        duplicates: number;
        dropped: number;
        drops: Partial<Record<DropReason, number>>;
        disabled: boolean;
        closed: boolean;
    };
    /** Wrap an actual handler. The callback's result and thrown error are preserved. */
    withTurn<T>(context: Context, input: string, operation: (trace: TraceContext) => Promise<T>, options?: {
        name?: string;
        model?: string;
        output?: (value: T) => string;
    }): Promise<T>;
    withTool<T>(context: Context, name: string, input: unknown, operation: () => Promise<T>): Promise<T>;
}
