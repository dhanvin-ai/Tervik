import { readFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { Tervik } from './tervik-client.mjs';

const MAX_SESSIONS = 64;
const MAX_TURNS = 128;
const MAX_SEEN = 4096;
const clip = value => String(value ?? '').slice(0, 32000);
const text = parts => clip(parts.filter(p => p.type === 'text' && !p.synthetic && !p.ignored).map(p => p.text).join('\n'));
const elapsed = time => Number.isFinite(time?.start) && Number.isFinite(time?.end) ? Math.max(0, time.end - time.start) : undefined;
const timestamp = value => Number.isFinite(value) ? new Date(value).toISOString() : undefined;
function boundedSet(map, key, value, limit) {
  map.delete(key);
  map.set(key, value);
  if (map.size > limit) map.delete(map.keys().next().value);
}
function redact(event) {
  // Add application-specific rules here before exporting conversation text.
  return JSON.parse(JSON.stringify(event).replace(/\b(?:tvk_|gh[pousr]_|github_pat_)[A-Za-z0-9_]+/g, '[REDACTED]'));
}

// tervik.instrumented: installed as an OpenCode plugin, not an application wrapper.
// Only export the plugin factory: OpenCode invokes each module export as a plugin.
export default async function TervikOpenCode({ client, directory }, options = {}) {
  const configPath = process.env.TERVIK_OPENCODE_CONFIG || join(process.env.XDG_CONFIG_HOME || join(homedir(), '.config'), 'opencode', 'tervik.json');
  let config = options.config;
  if (!config) {
    try { config = JSON.parse(await readFile(configPath, 'utf8')); }
    catch { config = {}; }
  }
  const log = async (level, message, extra = {}) => {
    try { await client.app.log({ body: { service: 'tervik', level, message, extra } }); }
    catch { /* Diagnostics must never break OpenCode. */ }
  };
  const telemetry = options.telemetry || new Tervik({
    apiKey: process.env.TERVIK_API_KEY || config.apiKey,
    endpoint: process.env.TERVIK_ENDPOINT || config.endpoint,
    redact,
    onDiagnostic: ({ code }) => { void log('warn', `Telemetry diagnostic: ${code}`); },
  });
  if (telemetry.inspect().disabled) {
    await log('warn', `Configure TERVIK_API_KEY and TERVIK_ENDPOINT or ${configPath}, then restart OpenCode.`);
    return { dispose: () => telemetry.shutdown() };
  }
  const userID = typeof config.userId === 'string' && config.userId ? config.userId.slice(0, 200) : randomUUID();
  const id = (...values) => createHash('sha256').update(JSON.stringify([userID, ...values])).digest('hex');
  const sessions = new Map();
  const seen = new Map();
  const pending = new Map();
  let closed = false;
  function capture(key, event) {
    if (seen.has(key)) return;
    if (telemetry.capture(redact({ ...event, id: id('event', key) })) !== null) boundedSet(seen, key, true, MAX_SEEN);
  }
  function context(sessionID, turnID) {
    return { conversation_id: `opencode:${sessionID}`, user_id: userID, trace_id: id('turn', sessionID, turnID) };
  }
  function track(message) {
    let turns = sessions.get(message.sessionID);
    if (!turns) {
      turns = new Map();
      boundedSet(sessions, message.sessionID, turns, MAX_SESSIONS);
    }
    boundedSet(turns, message.id, message.time?.created, MAX_TURNS);
  }
  function record(info, parts, allowPartial) {
    const turns = sessions.get(info.sessionID);
    if (!turns?.has(info.parentID) || info.role !== 'assistant' || info.summary) return;
    const ctx = context(info.sessionID, info.parentID);
    const spanID = id('assistant', info.sessionID, info.id);
    for (const part of parts) {
      if (part.type !== 'tool' || !['completed', 'error'].includes(part.state.status)) continue;
      const failed = part.state.status === 'error';
      // Tool arguments, output, attachments, paths and provider headers are intentionally omitted.
      capture(`tool:${info.sessionID}:${part.id}`, {
        ...ctx, span_id: id('tool', info.sessionID, part.id), parent_span_id: spanID,
        role: 'tool', name: String(part.tool).slice(0, 200), status: failed ? 'error' : 'success',
        content: `${part.tool}: ${part.state.status}`,
        timestamp: timestamp(part.state.time?.end), latency_ms: elapsed(part.state.time),
        metadata: { source: 'opencode', call_id: part.callID, capture: 'tool-metadata-only' },
      });
    }
    const complete = Number.isFinite(info.time?.completed);
    if (!complete && !allowPartial) return;
    const content = text(parts) || (info.error ? clip(info.error.data?.message || info.error.name) : '');
    const tokenValues = [info.tokens?.input, info.tokens?.output, info.tokens?.reasoning, info.tokens?.cache?.read, info.tokens?.cache?.write];
    const tokens = tokenValues.every(v => Number.isSafeInteger(v) && v >= 0) ? tokenValues.reduce((a, b) => a + b, 0) : undefined;
    capture(`assistant:${info.sessionID}:${info.id}`, {
      ...ctx, span_id: spanID, role: 'assistant', name: 'opencode.assistant',
      content, status: info.error ? 'error' : 'success', timestamp: timestamp(info.time?.created),
      latency_ms: elapsed({ start: info.time?.created, end: info.time?.completed }),
      model: String(info.modelID || '').slice(0, 200) || undefined,
      tokens, cost_usd: Number.isFinite(info.cost) && info.cost >= 0 ? info.cost : undefined,
      metadata: { source: 'opencode', ...(complete ? {} : { stream_partial: true }), ...(info.error ? { error_type: info.error.name } : {}) },
    });
  }
  async function sync(sessionID, partial) {
    const result = await client.session.messages({ path: { id: sessionID }, query: { directory, limit: 200 }, signal: AbortSignal.timeout(5000) });
    if (!Array.isArray(result.data)) throw new Error('message-read');
    for (const { info, parts } of result.data) {
      if (info.sessionID === sessionID) record(info, parts, partial);
    }
    await telemetry.flush();
    await log('info', 'OpenCode telemetry status', telemetry.inspect());
  }
  // Coalesce repeated status events. SDK reads and exports run outside the hook's critical path.
  function schedule(sessionID, partial = false) {
    if (closed || !sessions.has(sessionID)) return;
    const running = pending.get(sessionID);
    if (running) { running.again = true; running.partial ||= partial; return; }
    const job = { again: false, partial, promise: undefined };
    job.promise = new Promise(resolve => setTimeout(resolve, 0)).then(async () => {
      do {
        job.again = false;
        try { await sync(sessionID, job.partial); }
        catch { await log('warn', 'Could not read or export OpenCode messages; will retry on the next session event.'); }
      } while (job.again && !closed);
    }).finally(() => pending.delete(sessionID));
    pending.set(sessionID, job);
  }
  await log('info', 'Tervik OpenCode monitoring enabled. New turns only; tool payloads omitted.');
  return {
    'chat.message': async (_input, output) => {
      if (closed || !output.message?.id || !output.message.sessionID) return;
      try {
        track(output.message);
        capture(`user:${output.message.sessionID}:${output.message.id}`, {
          ...context(output.message.sessionID, output.message.id), role: 'user', content: text(output.parts),
          timestamp: timestamp(output.message.time?.created), metadata: { source: 'opencode' },
        });
      } catch { await log('warn', 'Could not capture OpenCode user message.'); }
    },
    event: async ({ event }) => {
      const props = event.properties;
      if (event.type === 'session.idle' || (event.type === 'session.status' && props.status?.type === 'idle') || event.type === 'session.error') {
        schedule(props.sessionID, true);
      } else if (event.type === 'message.updated' && props.info?.role === 'assistant' && props.info.time?.completed) {
        schedule(props.info.sessionID);
      } else if (event.type === 'session.deleted') {
        sessions.delete(props.info?.id);
      }
    },
    dispose: async () => {
      closed = true;
      await Promise.allSettled([...pending.values()].map(job => job.promise));
      await telemetry.shutdown();
    },
  };
}
