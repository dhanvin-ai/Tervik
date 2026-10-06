import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { Tervik } from '../dist/index.js';
import { Tervik as PortableTervik } from '../../../skills/tervik/scripts/tervik-client.mjs';

async function server(handler) {
  const requests = [];
  const http = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString());
    requests.push({ body, headers: request.headers, url: request.url });
    await handler(request, response, body, requests.length);
  });
  await new Promise(resolve => http.listen(0, '127.0.0.1', resolve));
  return { requests, endpoint: `http://127.0.0.1:${http.address().port}`, close: () => new Promise(resolve => http.close(resolve)) };
}
function client(endpoint, overrides = {}) {
  return new Tervik({ endpoint, apiKey: 'project-test-key', flushIntervalMs: 0, retryBaseMs: 1, maxRetryDelayMs: 5, onDiagnostic() {}, onDrop() {}, ...overrides });
}
function ok(response, body) {
  response.writeHead(200, { 'content-type': 'application/json' });
  response.end(JSON.stringify({ accepted: body.events.length, duplicates: 0 }));
}

test('captures snapshots, redacts before export, follows the API and batches at 100', async () => {
  const api = await server((_request, response, body) => ok(response, body));
  try {
    const sdk = client(api.endpoint);
    const metadata = { api_key: 'super-secret', input: { password: 'hidden', authorization: 'Bearer abc123' } };
    const id = sdk.capture({ conversation_id: 'conv-1', user_id: 'anon-1', role: 'user', content: 'token Bearer abc123', metadata });
    metadata.input.password = 'changed-after-capture';
    for (let i = 0; i < 100; i++) sdk.capture({ conversation_id: 'conv-1', role: 'assistant', content: `answer-${i}` });
    const result = await sdk.flush();
    assert.equal(result.accepted, 101);
    assert.deepEqual(api.requests.map(item => item.body.events.length), [100, 1]);
    const first = api.requests[0];
    assert.equal(first.url, '/v1/events');
    assert.equal(first.headers.authorization, 'Bearer project-test-key');
    assert.equal(first.body.events[0].id, id);
    assert.equal(first.body.events[0].content, 'token Bearer [REDACTED]');
    assert.equal(first.body.events[0].metadata.api_key, '[REDACTED]');
    assert.equal(first.body.events[0].metadata.input.password, '[REDACTED]');
    assert.ok(first.body.events[0].timestamp.endsWith('Z'));
    assert.equal(JSON.stringify(first.body).includes('project-test-key'), false);
    await sdk.shutdown();
  } finally { await api.close(); }
});

test('retries 503/429 with the same IDs and handles duplicate acknowledgements', async () => {
  const api = await server((_request, response, body, attempt) => {
    if (attempt < 3) { response.writeHead(attempt === 1 ? 503 : 429, { 'retry-after': '0' }); response.end(); }
    else { response.writeHead(200, { 'content-type': 'application/json' }); response.end(JSON.stringify({ accepted: 0, duplicates: body.events.length })); }
  });
  try {
    const sdk = client(api.endpoint);
    sdk.capture({ conversation_id: 'retry', role: 'user', content: 'hello' });
    const result = await sdk.flush();
    assert.equal(api.requests.length, 3);
    assert.equal(result.duplicates, 1);
    assert.equal(new Set(api.requests.map(item => item.body.events[0].id)).size, 1);
    assert.equal(new Set(api.requests.map(item => JSON.stringify(item.body))).size, 1);
    await sdk.shutdown();
  } finally { await api.close(); }
});

test('does not retry invalid authentication and reports all dropped events', async () => {
  const api = await server((_request, response) => { response.writeHead(401); response.end(); });
  try {
    const notices = [];
    const sdk = client(api.endpoint, { maxBatchSize: 1, onDrop: notice => notices.push(notice) });
    sdk.capture({ conversation_id: 'auth', role: 'user', content: 'one' });
    sdk.capture({ conversation_id: 'auth', role: 'assistant', content: 'two' });
    const result = await sdk.flush();
    assert.equal(result.dropped, 2);
    assert.equal(api.requests.length, 1);
    assert.equal(sdk.inspect().disabled, true);
    assert.equal(sdk.capture({ conversation_id: 'auth', role: 'tool', content: 'three' }), null);
    assert.equal(notices.reduce((count, notice) => count + notice.count, 0), 3);
  } finally { await api.close(); }
});

test('bounds its queue, rejects malformed events locally and isolates redaction errors', async () => {
  const sdk = client('http://127.0.0.1:9', { maxQueueSize: 2 });
  sdk.capture({ conversation_id: 'queue', role: 'user', content: 'one' });
  sdk.capture({ conversation_id: 'queue', role: 'user', content: 'two' });
  assert.equal(sdk.capture({ conversation_id: 'queue', role: 'user', content: 'three' }), null);
  assert.equal(sdk.capture({ conversation_id: 'queue', role: 'user', content: 'bad', cost_usd: -1 }), null);
  assert.equal(sdk.inspect().queued, 2);
  assert.equal(sdk.inspect().drops.queue_full, 1);
  assert.equal(sdk.inspect().drops.invalid_event, 1);
  const redactor = client('http://127.0.0.1:9', { redact() { throw new Error('private detail'); } });
  assert.doesNotThrow(() => redactor.capture({ conversation_id: 'redact', role: 'user', content: 'private' }));
  assert.equal(redactor.inspect().drops.redaction, 1);
  const empty = client('http://127.0.0.1:9', { apiKey: '' });
  assert.equal(empty.capture({ conversation_id: 'key', role: 'user', content: 'hello' }), null);
  assert.equal(empty.inspect().drops.configuration, 1);
});

test('preserves actual handler output and original errors with parented tool spans', async () => {
  const api = await server((_request, response, body) => ok(response, body));
  try {
    const sdk = client(api.endpoint);
    const value = { answer: 'actual answer' };
    const result = await sdk.withTurn({ conversation_id: 'real', user_id: 'pseudo' }, 'actual request', async trace => {
      const tool = await sdk.withTool(trace, 'lookup', { query: 'actual query' }, async () => ({ found: true }));
      assert.equal(tool.found, true);
      return value;
    }, { output: output => output.answer });
    assert.equal(result, value);
    const original = new Error('actual tool failure');
    await assert.rejects(sdk.withTurn({ conversation_id: 'error' }, 'failed request', trace => sdk.withTool(trace, 'failing_tool', {}, async () => { throw original; })), error => error === original);
    await sdk.flush();
    const events = api.requests[0].body.events;
    const turn = events.find(event => event.conversation_id === 'real' && event.role === 'assistant');
    const tool = events.find(event => event.conversation_id === 'real' && event.role === 'tool');
    assert.equal(tool.parent_span_id, turn.span_id);
    assert.equal(tool.trace_id, turn.trace_id);
    assert.equal(turn.content, 'actual answer');
    assert.equal(turn.status, 'success');
    assert.ok(tool.latency_ms >= 0);
    assert.equal(events.filter(event => event.conversation_id === 'error' && event.status === 'error').length, 2);
    await sdk.shutdown();
  } finally { await api.close(); }
});

test('finite retries, single concurrent drain, callback isolation and shutdown semantics', async () => {
  const api = await server((_request, response) => { response.writeHead(503); response.end(); });
  try {
    const sdk = client(api.endpoint, { maxRetries: 1, onDrop() { throw new Error('callback error'); }, onDiagnostic() { throw new Error('callback error'); } });
    sdk.capture({ conversation_id: 'finite', role: 'user', content: 'hello' });
    const first = sdk.flush();
    assert.equal(sdk.flush(), first);
    const result = await first;
    assert.equal(api.requests.length, 2);
    assert.equal(result.dropped, 1);
    await sdk.shutdown();
    assert.equal(sdk.capture({ conversation_id: 'closed', role: 'user', content: 'late' }), null);
    assert.equal(sdk.inspect().closed, true);
  } finally { await api.close(); }
});

test('telemetry cannot replace a successful result when its output mapper throws', async () => {
  const api = await server((_request, response, body) => ok(response, body));
  try {
    const sdk = client(api.endpoint);
    const result = await sdk.withTurn({ conversation_id: 'mapping' }, 'actual input', async () => 42, { output() { throw new Error('mapping'); } });
    assert.equal(result, 42);
    await sdk.shutdown();
    assert.equal(api.requests[0].body.events.at(-1).content, '[OUTPUT MAPPING FAILED]');
  } finally { await api.close(); }
});

test('the downloadable dependency-free client instruments an existing handler', async () => {
  const api = await server((_request, response, body) => ok(response, body));
  try {
    const sdk = new PortableTervik({ apiKey: 'project-test-key', endpoint: api.endpoint, flushIntervalMs: 0, onDrop() {}, onDiagnostic() {} });
    const existingTool = async query => ({ answer: `Result for ${query}` });
    const existingHandler = async request => sdk.withTurn({ conversation_id: request.conversationId, user_id: request.userId }, request.message, async trace => {
      const result = await sdk.withTool(trace, 'existing.lookup', { query: request.message }, () => existingTool(request.message));
      return result.answer;
    });
    assert.equal(await existingHandler({ conversationId: 'fixture-real-handler', userId: 'pseudo', message: 'Find my order' }), 'Result for Find my order');
    await sdk.shutdown();
    assert.deepEqual(api.requests[0].body.events.map(event => event.role), ['user', 'tool', 'assistant']);
    assert.equal(api.requests[0].body.events[2].content, 'Result for Find my order');
  } finally { await api.close(); }
});

test('streams chunks untouched while recording one assistant event', async () => {
  const api = await server((_request, response, body) => ok(response, body));
  try {
    const sdk = client(api.endpoint);
    async function* chunks() { yield 'Hel'; yield 'lo'; }
    const seen = [];
    for await (const chunk of sdk.withStream({ conversation_id: 'stream' }, 'Hi', chunks())) seen.push(chunk);
    assert.deepEqual(seen, ['Hel', 'lo']);
    await sdk.flush();
    const events = api.requests[0].body.events;
    assert.deepEqual(events.map(event => event.role), ['user', 'assistant']);
    assert.equal(events[1].content, 'Hello');
    assert.equal(events[1].status, 'success');
    assert.equal(events[1].trace_id, events[0].trace_id);
    await sdk.shutdown();
  } finally { await api.close(); }
});

test('streaming errors and early termination record the actual outcome', async () => {
  const api = await server((_request, response, body) => ok(response, body));
  try {
    const sdk = client(api.endpoint);
    const failure = new Error('mid-stream failure');
    async function* failing() { yield 'part'; throw failure; }
    await assert.rejects(async () => { for await (const _ of sdk.withStream({ conversation_id: 'stream-err' }, 'Hi', failing())); }, error => error === failure);
    async function* endless() { yield 'a'; yield 'b'; }
    for await (const _ of sdk.withStream({ conversation_id: 'stream-cancel' }, 'Hi', endless())) break;
    await sdk.flush();
    const events = api.requests[0].body.events;
    const failed = events.find(event => event.conversation_id === 'stream-err' && event.role === 'assistant');
    assert.equal(failed.status, 'error');
    assert.equal(failed.content, 'mid-stream failure');
    const cancelled = events.find(event => event.conversation_id === 'stream-cancel' && event.role === 'assistant');
    assert.equal(cancelled.status, 'success');
    assert.equal(cancelled.metadata.stream_cancelled, true);
    await sdk.shutdown();
  } finally { await api.close(); }
});

test('rejects backend-invalid fields locally without poisoning valid events in the batch', async () => {
  const api = await server((_request, response, body) => ok(response, body));
  try {
    const sdk = client(api.endpoint);
    const valid = { conversation_id: 'valid-source', role: 'user', content: 'Actual request', tokens: 3 };
    const invalid = [
      { tokens: 3.5 }, { tokens: true }, { name: 'x'.repeat(201) },
      { id: 'x'.repeat(201) }, { conversation_id: 'x'.repeat(201) },
      { metadata: { value: Infinity } }, { project_id: 'not-authorization' },
      { timestamp: '2026-10-06T12:00:00' },
      { timestamp: new Date(Date.now() + 10 * 60 * 1000).toISOString() }
    ];
    for (const fields of invalid) assert.equal(sdk.capture({ ...valid, ...fields }), null);
    assert.ok(sdk.capture(valid));
    const result = await sdk.flush();
    assert.equal(result.accepted, 1);
    assert.equal(api.requests.length, 1);
    assert.equal(api.requests[0].body.events.length, 1);
    assert.equal(api.requests[0].body.events[0].tokens, 3);
    assert.equal(sdk.inspect().drops.invalid_event, invalid.length);
    await sdk.shutdown();
  } finally { await api.close(); }
});
