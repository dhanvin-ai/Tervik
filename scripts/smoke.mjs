import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, rm } from 'node:fs/promises';
import net from 'node:net';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { Tervik } from '../packages/sdk/dist/index.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = path.join(root, 'apps/api/.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
if (!existsSync(python)) throw new Error('Run npm run setup:api first.');
await mkdir(path.join(root, '.data'), { recursive: true });
const directory = await mkdtemp(path.join(root, '.data/smoke-'));
const reservation = net.createServer();
reservation.listen(0, '127.0.0.1');
await once(reservation, 'listening');
const port = reservation.address().port;
await new Promise(resolve => reservation.close(resolve));
const endpoint = `http://127.0.0.1:${port}`;
const admin = randomUUID();
let child;
let logs = '';

async function start() {
  child = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--app-dir', 'apps/api', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: root,
    env: { ...process.env, DATABASE_URL: `sqlite:///${path.join(directory, 'smoke.db')}`, TERVIK_ADMIN_TOKEN: admin, TERVIK_DEMO_ENABLED: 'false', CLICKHOUSE_URL: '' },
    stdio: ['ignore', 'pipe', 'pipe']
  });
  logs = '';
  child.stdout.on('data', chunk => { logs = (logs + chunk).slice(-8000); });
  child.stderr.on('data', chunk => { logs = (logs + chunk).slice(-8000); });
  child.on('error', error => { logs += error.message; });
  for (let attempt = 0; attempt < 100; attempt++) {
    try {
      const response = await fetch(`${endpoint}/api/health`, { signal: AbortSignal.timeout(1000) });
      if (response.ok) return;
    } catch { /* Startup poll only. */ }
    if (child.exitCode !== null) throw new Error(`API exited during startup: ${logs}`);
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`API did not start: ${logs}`);
}

async function stop() {
  if (!child || child.exitCode !== null) return;
  const exited = once(child, 'exit');
  child.kill('SIGTERM');
  const timer = setTimeout(() => child.kill('SIGKILL'), 4000);
  await exited;
  clearTimeout(timer);
}

async function request(route, { method = 'GET', body, key = admin, status = 200 } = {}) {
  const response = await fetch(endpoint + route, {
    method,
    headers: { 'content-type': 'application/json', ...(key ? { authorization: `Bearer ${key}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(5000)
  });
  assert.equal(response.status, status, `${method} ${route}: ${await (response.status === status ? Promise.resolve('') : response.text())}`);
  return response.json();
}

try {
  await start();
  const project = await request('/api/projects', { method: 'POST', body: { name: 'SDK smoke test' }, status: 201 });
  assert.ok(project.api_key);
  const second = await request('/api/projects', { method: 'POST', body: { name: 'Isolation test' }, status: 201 });
  const client = new Tervik({ apiKey: project.api_key, endpoint, flushIntervalMs: 0 });
  const time = offset => new Date(Date.now() - 120000 + offset).toISOString();
  const events = [
    { id: 'smoke-user-1', conversation_id: 'session-shared', user_id: 'user-1', role: 'user', content: 'Can I keep all twelve projects if I downgrade?', timestamp: time(0) },
    { id: 'smoke-assistant-1', conversation_id: 'session-shared', user_id: 'user-1', role: 'assistant', content: 'All twelve projects will stay active.', timestamp: time(1000), trace_id: 'trace-1', span_id: 'turn-1', name: 'agent.turn', latency_ms: 400, model: 'test-model', cost_usd: 0.001 },
    { id: 'smoke-user-2', conversation_id: 'session-shared', user_id: 'user-1', role: 'user', content: "That's wrong. The free plan only keeps three projects.", timestamp: time(2000) },
    { id: 'smoke-tool-1', conversation_id: 'session-shared', user_id: 'user-1', role: 'tool', content: 'Provider unavailable', timestamp: time(3000), trace_id: 'trace-1', span_id: 'tool-1', parent_span_id: 'turn-1', name: 'lookup_policy', status: 'error', latency_ms: 50, metadata: { input: { plan: 'free' }, output: { error: 'Provider unavailable' } } }
  ];
  for (const event of events) assert.ok(client.capture(event));
  const flushed = await client.flush();
  assert.equal(flushed.accepted, 4);
  assert.equal(flushed.dropped, 0);
  const duplicate = await request('/v1/events', { method: 'POST', key: project.api_key, body: { events } });
  assert.deepEqual(duplicate, { accepted: 0, duplicates: 4 });
  const overview = await request(`/api/overview?project_id=${project.id}&range=7d`);
  assert.equal(overview.metrics.conversations, 1);
  assert.equal(overview.metrics.messages, 4);
  assert.equal(overview.metrics.failure_rate, 100);
  assert.equal(overview.metrics.affected_users, 1);
  const clusters = await request(`/api/clusters?project_id=${project.id}&range=7d`);
  assert.ok(clusters.some(cluster => cluster.kind === 'correction'));
  assert.ok(clusters.some(cluster => cluster.kind === 'tool_error'));
  const conversations = await request(`/api/conversations?project_id=${project.id}&range=7d`);
  const detail = await request(`/api/conversations/${conversations[0].id}`);
  assert.equal(detail.messages.length, 4);
  assert.equal(detail.spans.find(span => span.id === 'tool-1').parent_id, 'turn-1');
  const resolved = await request(`/api/clusters/${clusters[0].id}`, { method: 'PATCH', body: { status: 'resolved' } });
  assert.equal(resolved.status, 'resolved');
  await request('/v1/events', { method: 'POST', key: '', body: { events }, status: 401 });
  await request('/api/projects', { key: project.api_key, status: 401 });
  await request('/api/demo/seed', { method: 'POST', status: 404 });
  const other = await request('/v1/events', { method: 'POST', key: second.api_key, body: { events: [events[0]] } });
  assert.equal(other.accepted, 1);
  const otherConversations = await request(`/api/conversations?project_id=${second.id}`);
  assert.notEqual(otherConversations[0].id, conversations[0].id);
  assert.equal((await request(`/api/overview?project_id=${second.id}`)).metrics.messages, 1);
  await client.shutdown();
  console.log('PASS: SDK → authenticated ingestion → persisted conversations → evidence/trace → cluster review.');
  await stop();
  await start();
  assert.equal((await request(`/api/overview?project_id=${project.id}`)).metrics.messages, 4);
  assert.equal((await request(`/api/clusters/${clusters[0].id}`)).status, 'resolved');
  console.log('PASS: project boundaries, retry deduplication, administrator separation, and restart durability.');
} finally {
  await stop();
  await rm(directory, { recursive: true, force: true });
}
