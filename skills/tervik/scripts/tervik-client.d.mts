export declare const SDK_VERSION = "0.1.0";
export declare const SDK_NAME = "@tervik/sdk";
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
    /**
     * Wrap an actual streaming operation. The original iterator is preserved:
     * chunks are yielded to the caller untouched while permitted text is
     * accumulated for one assistant event. Early termination records a partial
     * outcome; errors record the actual failure. Telemetry never throws.
     */
    withStream<T>(context: Context, input: string, stream: AsyncIterable<T>, options?: {
        name?: string;
        model?: string;
        textOf?: (chunk: T) => string;
        output?: (full: string) => string;
    }): AsyncGenerator<T, void, unknown>;
}
export interface InteractionOptions {
    /** Project ingest key. When set it is sent instead of the project ID. */
    apiKey?: string;
    /** Base origin, e.g. http://127.0.0.1:8000. */
    endpoint?: string;
    debug?: boolean;
    flushIntervalMs?: number;
    requestTimeoutMs?: number;
    maxRetries?: number;
    retryBaseMs?: number;
    maxQueueSize?: number;
    /** Runs on each capture-event body before it is queued; return null to drop it. */
    redact?: (body: CaptureEventBody) => CaptureEventBody | null;
}
export interface BeginOptions {
    userId: string;
    agentName?: string;
    input?: unknown;
    conversationId?: string;
    interactionId?: string;
}
export interface TrackOptions {
    userId: string;
    input?: unknown;
    output?: unknown;
    agentName?: string;
    conversationId?: string;
    success?: boolean;
    latencyMs?: number;
    properties?: Record<string, unknown>;
}
export interface CaptureEventBody {
    event_id: string;
    session_id: string;
    primitive_name: string;
    args: string;
    result: string;
    success: boolean;
    latency: number;
    timestamp: number;
    parent_id?: string;
    metadata: Record<string, string>;
}
export interface InteractionStats {
    sent: number;
    dropped: number;
    pending: number;
}
declare abstract class Operation {
    protected readonly client: InteractionClient;
    readonly id: string;
    output: unknown;
    readonly properties: Record<string, unknown>;
    protected readonly startedAt: number;
    protected readonly started: number;
    protected ended: boolean;
    protected constructor(client: InteractionClient, id?: string);
    abstract get conversationId(): string;
    setProperty(key: string, value: unknown): this;
    setProperties(values: Record<string, unknown>): this;
    /** Start a nested tool call. End it, or pass a function to `run`. */
    tool(name: string, input?: unknown): ToolCall;
}
export declare class ToolCall extends Operation {
    private readonly parent;
    readonly name: string;
    readonly input: unknown;
    constructor(client: InteractionClient, parent: Operation, name: string, input: unknown);
    get conversationId(): string;
    end(output?: unknown, success?: boolean): void;
    /** Run the tool, record its result or error, and return or rethrow it unchanged. */
    run<T>(operation: () => T | Promise<T>): Promise<T>;
}
export declare class Interaction extends Operation {
    readonly userId: string;
    readonly agentName: string;
    readonly input: unknown;
    readonly conversationId: string;
    constructor(client: InteractionClient, userId: string, agentName: string, input: unknown, conversationId?: string, interactionId?: string);
    end(output?: unknown, success?: boolean, latencyMs?: number): void;
}
/** Bounded FIFO of capture requests. A session is queued before its events. */
export declare class InteractionClient {
    private readonly projectId;
    private readonly options;
    disabled?: 'configuration' | 'authentication';
    private readonly base;
    private readonly queue;
    private readonly open;
    private readonly sessions;
    private readonly userSessions;
    private readonly traits;
    private readonly timer?;
    private flushing?;
    private closed;
    private sent;
    private dropped;
    constructor(projectId?: string, options?: InteractionOptions);
    begin({ userId, agentName, input, conversationId, interactionId }: BeginOptions): Interaction;
    track({ userId, input, output, agentName, conversationId, success, latencyMs, properties }: TrackOptions): string;
    /** Attach traits to a user; they are sent with the user's sessions. */
    identify(userId: string, traits?: Record<string, unknown>): void;
    getInteraction(interactionId: string): Interaction | undefined;
    /** @internal */
    forget(interactionId: string): void;
    /** @internal */
    event(conversationId: string, eventId: string, name: string, input: unknown, output: unknown, success: boolean, latencyMs: number, startedAt: number, properties: Record<string, unknown>, parentId?: string): void;
    flush(): Promise<InteractionStats>;
    shutdown(): Promise<InteractionStats>;
    private drain;
    private queueSession;
    private push;
    private drop;
    private send;
}
/** Configure the module-level client. Call once, before tracking. */
export declare function init(projectId?: string, options?: InteractionOptions): InteractionClient;
export declare function begin(options: BeginOptions): Interaction;
export declare function track(options: TrackOptions): string;
export declare function identify(userId: string, traits?: Record<string, unknown>): void;
export declare function getInteraction(interactionId: string): Interaction | undefined;
export declare function flush(): Promise<InteractionStats>;
export declare function shutdown(): Promise<InteractionStats>;
export {};
