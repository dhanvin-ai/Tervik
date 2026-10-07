import test from 'node:test';
import assert from 'node:assert/strict';
import plugin from '../../../skills/tervik/scripts/opencode-plugin.mjs';
import { Tervik } from '../../../skills/tervik/scripts/tervik-client.mjs';

const created = Date.now() - 1000;
function assistant(sessionID, parentID, extra = {}) {
  return { info: { id: `reply-${parentID}`, sessionID, parentID, role: 'assistant', time: { created, completed: created + 500 }, modelID: 'actual-model', cost: 0.02, tokens: { input: 3, output: 4, reasoning: 1, cache: { read: 2, write: 0 } }, ...extra }, parts: [{ type: 'text', text: 'Real reply', id: 'text-1' }] };
}
async function start(rows, overrides = {}) {
  const events = [];
  const telemetry = {
    capture(event) { events.push(event); return event.id; },
    inspect() { return { disabled: false, accepted: events.length, dropped: 0 }; },
    async flush() {}, async shutdown() {},
  };
  const client = { app: { log: async () => {} }, session: { messages: async () => ({ data: rows }) }, ...overrides };
  const hooks = await plugin({ client, directory: '/application' }, { config: { userId: 'pseudonymous-installation' }, telemetry });
  return { hooks, events };
}
async function user(hooks, sessionID, id, content = 'Help me') {
  await hooks['chat.message']({ sessionID }, { message: { id, sessionID, role: 'user', time: { created } }, parts: [{ type: 'text', text: content }, { type: 'file', url: 'file:///secret' }, { type: 'text', text: 'synthetic secret', synthetic: true }] });
}
const idle = (hooks, sessionID) => hooks.event({ event: { type: 'session.status', properties: { sessionID, status: { type: 'idle' } } } });

// Test fixtures exercise the adapter, not verification traffic in a customer's project.
test('real message identities correlate tool success/errors and omit credential-bearing payloads', async () => {
  const row = assistant('session-1', 'user-1');
  row.parts.push(...['completed', 'error'].map((status, i) => ({ type: 'tool', id: `tool-${i}`, callID: `call-${i}`, tool: 'bash', state: { status, time: { start: created + 100, end: created + 200 }, input: { command: 'printenv' }, output: 'SECRET_FILE_CONTENT', error: 'SECRET_ERROR', metadata: { headers: { Authorization: 'SECRET_HEADER' } } } })));
  const { hooks, events } = await start([assistant('session-1', 'old-user'), row]);
  await user(hooks, 'session-1', 'user-1', 'key tvk_credential123');
  await idle(hooks, 'session-1');
  await hooks.dispose();
  assert.equal(events.length, 4);
  const [u, success, error, a] = events;
  assert.equal(u.content, 'key [REDACTED]');
  assert.equal(a.content, 'Real reply');
  assert.equal(a.tokens, 10);
  assert.equal(a.model, 'actual-model');
  assert.equal(a.latency_ms, 500);
  assert.equal(success.status, 'success');
  assert.equal(error.status, 'error');
  assert.equal(success.parent_span_id, a.span_id);
  assert.equal(error.trace_id, u.trace_id);
  assert.equal(a.trace_id, u.trace_id);
  assert.equal(a.conversation_id, 'opencode:session-1');
  assert.doesNotMatch(JSON.stringify(events), /SECRET_|printenv|synthetic secret|file:\/\/\/secret/);
});

test('coalesces completion and idle notifications; sessions and turns stay separate', async () => {
  const rows = [assistant('one', 'u1'), assistant('one', 'u2'), assistant('two', 'u3')];
  const { hooks, events } = await start(rows);
  await user(hooks, 'one', 'u1');
  await user(hooks, 'one', 'u2');
  await user(hooks, 'two', 'u3');
  await Promise.all([idle(hooks, 'one'), idle(hooks, 'one'), idle(hooks, 'two')]);
  await hooks.event({ event: { type: 'message.updated', properties: { info: rows[0].info } } });
  await hooks.dispose();
  assert.equal(events.length, 6);
  assert.equal(new Set(events.map(e => e.id)).size, 6);
  assert.equal(new Set(events.map(e => e.trace_id)).size, 3);
  assert.equal(new Set(events.map(e => e.conversation_id)).size, 2);
});

test('does not export historical sessions; incomplete assistant exports once on idle', async () => {
  const row = assistant('one', 'u1', { time: { created } });
  const { hooks, events } = await start([row]);
  await idle(hooks, 'one');
  assert.equal(events.length, 0);
  await user(hooks, 'one', 'u1');
  await hooks.event({ event: { type: 'message.updated', properties: { info: row.info } } });
  assert.equal(events.length, 1);
  await idle(hooks, 'one');
  await hooks.dispose();
  assert.equal(events.length, 2);
  assert.equal(events[1].metadata.stream_partial, true);
  assert.equal(events[1].latency_ms, undefined);
});

test('records actual provider errors without headers; observer failures do not break hooks', async () => {
  const row = assistant('one', 'u1', { error: { name: 'APIError', data: { message: 'Request failed', responseHeaders: { Authorization: 'SECRET_HEADER' }, responseBody: 'SECRET_BODY' } } });
  const { hooks, events } = await start([row]);
  await user(hooks, 'one', 'u1');
  await idle(hooks, 'one');
  await hooks.dispose();
  assert.equal(events[1].status, 'error');
  assert.equal(events[1].metadata.error_type, 'APIError');
  assert.doesNotMatch(JSON.stringify(events), /SECRET_/);
  const failed = await start([], { session: { messages: async () => { throw new Error('SDK unavailable'); } } });
  await user(failed.hooks, 'two', 'u2');
  await idle(failed.hooks, 'two');
  await failed.hooks.dispose();
});

test('SDK reads never delay event hooks and disposal waits for the pending export', async () => {
  let resolveRead;
  let started;
  const waiting = new Promise(resolve => { started = resolve; });
  const read = new Promise(resolve => { resolveRead = resolve; });
  const { hooks, events } = await start([], { session: { messages: () => { started(); return read; } } });
  await user(hooks, 'one', 'u1');
  await idle(hooks, 'one');
  await waiting;
  assert.equal(events.length, 1);
  let disposed = false;
  const shutdown = hooks.dispose().then(() => { disposed = true; });
  assert.equal(disposed, false);
  resolveRead({ data: [assistant('one', 'u1')] });
  await shutdown;
  assert.equal(events.length, 2);
});

test('portable exporter accepts adapter events, redacts common secrets, and preserves IDs on retries', async () => {
  const oldFetch = globalThis.fetch;
  const deliveries = [];
  globalThis.fetch = async (_url, options) => {
    const batch = JSON.parse(options.body).events;
    deliveries.push(batch);
    if (deliveries.length === 1) return new Response('', { status: 503 });
    return Response.json({ accepted: batch.length, duplicates: 0 });
  };
  const telemetry = new Tervik({ apiKey: 'test-key', endpoint: 'http://127.0.0.1:8000', flushIntervalMs: 0, retryBaseMs: 0, maxRetries: 1 });
  try {
    const hooks = await plugin({ directory: '/app', client: { app: { log: async () => {} }, session: { messages: async () => ({ data: [assistant('one', 'u1')] }) } } }, { config: { userId: 'pseudo' }, telemetry });
    await user(hooks, 'one', 'u1', 'password=secret123');
    await idle(hooks, 'one');
    await hooks.dispose();
    assert.equal(telemetry.inspect().dropped, 0);
    assert.equal(telemetry.inspect().accepted, 2);
    assert.equal(deliveries.length, 2);
    assert.deepEqual(deliveries[0], deliveries[1]);
    assert.doesNotMatch(JSON.stringify(deliveries), /secret123/);
  } finally { globalThis.fetch = oldFetch; await telemetry.shutdown(); }
});
