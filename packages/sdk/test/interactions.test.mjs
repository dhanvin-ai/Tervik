import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import * as tervik from '../dist/index.js';

async function server(status = () => 200) {
  const requests = [];
  const http = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    requests.push({ url: request.url, headers: request.headers, body: JSON.parse(Buffer.concat(chunks).toString()) });
    response.writeHead(status(request.url, requests.length), { 'content-type': 'application/json' });
    response.end('{}');
  });
  await new Promise(resolve => http.listen(0, '127.0.0.1', resolve));
  return { requests, endpoint: `http://127.0.0.1:${http.address().port}`, close: () => new Promise(resolve => http.close(resolve)) };
}
const options = endpoint => ({ endpoint, flushIntervalMs: 0, retryBaseMs: 1 });

test('a turn with nested tool calls sends its session first', async () => {
  const api = await server();
  try {
    const sdk = new tervik.InteractionClient('project-123', options(api.endpoint));
    const turn = sdk.begin({ userId: 'u-1', agentName: 'support', input: 'Where is order 42?', conversationId: 'c-1' });
    turn.setProperties({ model: 'gpt-4.1', tokens: 150, api_key: 'nope' });
    const lookup = turn.tool('orders.lookup', { order_id: 42 });
    const inner = lookup.tool('db.query', 'select 1');
    inner.end([1]);
    assert.deepEqual(await lookup.run(async () => ({ status: 'shipped' })), { status: 'shipped' });
    turn.end('It ships tomorrow.');
    turn.end('ignored');
    await sdk.flush();
    assert.deepEqual(api.requests.map(r => r.url), ['/api/v1/capture-session', '/api/v1/capture-event', '/api/v1/capture-event', '/api/v1/capture-event']);
    assert.ok(api.requests.every(r => r.headers['x-org-id'] === 'project-123'));
    assert.deepEqual(api.requests[0].body.user_data, { user_id: 'u-1' });
    const [innerEvent, toolEvent, turnEvent] = api.requests.slice(1).map(r => r.body);
    assert.equal(innerEvent.parent_id, toolEvent.event_id);
    assert.equal(toolEvent.parent_id, turnEvent.event_id);
    assert.equal(toolEvent.result, '{"status":"shipped"}');
    assert.equal(turnEvent.parent_id, undefined);
    assert.equal(turnEvent.result, 'It ships tomorrow.');
    assert.deepEqual(turnEvent.metadata, { model: 'gpt-4.1', tokens: '150', api_key: '[REDACTED]' });
  } finally { await api.close(); }
});

test('failures, track, identify and interaction lookup', async () => {
  const api = await server();
  try {
    const sdk = new tervik.InteractionClient('', { ...options(api.endpoint), apiKey: 'tvk_secret' });
    sdk.track({ userId: 'u-2', input: 'hi', output: 'hello', agentName: 'greeter', latencyMs: 12.5 });
    sdk.identify('u-2', { plan: 'pro' });
    const turn = sdk.begin({ userId: 'u-2', input: 'Pay invoice', interactionId: 'req-1' });
    assert.equal(sdk.getInteraction('req-1'), turn);
    await assert.rejects(turn.tool('payments.charge').run(() => { throw new Error('gateway timed out'); }), /timed out/);
    sdk.getInteraction('req-1').end('Payment failed', false);
    assert.equal(sdk.getInteraction('req-1'), undefined);
    await sdk.flush();
    assert.ok(api.requests.every(r => r.headers.authorization === 'Bearer tvk_secret'));
    const events = api.requests.filter(r => r.url.endsWith('capture-event')).map(r => r.body);
    assert.equal(events.find(e => e.primitive_name === 'greeter').latency, 12.5);
    assert.equal(events.find(e => e.primitive_name === 'payments.charge').success, false);
    assert.equal(events.find(e => e.args === 'Pay invoice').success, false);
    const withTrait = api.requests.filter(r => r.url.endsWith('capture-session') && r.body.user_data.plan === 'pro');
    assert.equal(withTrait.length, 2);
  } finally { await api.close(); }
});

test('rejected credentials disable capture and misconfiguration never throws', async () => {
  const api = await server(() => 401);
  const warn = console.warn;
  console.warn = () => {};
  try {
    const sdk = new tervik.InteractionClient('project-x', options(api.endpoint));
    sdk.track({ userId: 'u', input: 'a', output: 'b' });
    await sdk.flush();
    assert.equal(sdk.disabled, 'authentication');
    sdk.track({ userId: 'u', input: 'c', output: 'd' });
    await sdk.flush();
    assert.equal(api.requests.length, 1);
    const broken = new tervik.InteractionClient('', { endpoint: 'ftp://nowhere', flushIntervalMs: 0 });
    assert.equal(broken.disabled, 'configuration');
    broken.begin({ userId: 'u', input: 'x' }).end('y');
    assert.equal((await broken.flush()).pending, 0);
  } finally { console.warn = warn; await api.close(); }
});

test('module-level init, identify, track and shutdown', async () => {
  const api = await server();
  try {
    tervik.init('project-9', options(api.endpoint));
    tervik.identify('u-9', { role: 'admin' });
    tervik.track({ userId: 'u-9', input: 'hi', output: 'hello', conversationId: 'c-9' });
    await tervik.shutdown();
    assert.deepEqual(api.requests[0].body.user_data, { role: 'admin', user_id: 'u-9' });
    assert.equal(api.requests[1].body.session_id, 'c-9');
  } finally { await api.close(); }
});
