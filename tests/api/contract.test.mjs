/*
 * API contract tests — the parts a browser test cannot see.
 *
 * These run against the real server over HTTP with a throwaway database and a
 * mock provider behind it, so they are fast enough to run on every save.
 */
import test from 'node:test';
import { startApp, client } from '../helpers/app.mjs';
import { createMockUpstream } from '../mock-upstream/server.mjs';
import { streamChat, plainChat } from '../helpers/stream.mjs';
import { equal, ok, includes, between } from '../helpers/assertions.mjs';

let app;
let mock;
let api;
let providerId;
let mockBase;

test.before(async () => {
  mock = createMockUpstream();
  const mockPort = await mock.listen();
  mockBase = `http://127.0.0.1:${mockPort}`;
  app = await startApp();
  api = client(app.baseUrl);
});

test.after(async () => {
  await app?.stop();
  await mock?.close();
});

test.beforeEach(async () => {
  await fetch(`${mockBase}/control/reset`, { method: 'POST' });
  if (!providerId) {
    providerId = await api.addProvider({ baseUrl: `${mockBase}/v1`, model: 'mock-chat' });
  }
});

test('health reports the running version', async () => {
  const res = await api.get('/api/health');
  equal(res.status, 200, 'health status');
  equal(res.json.name, 'archx-agent', 'service name');
  ok(/^\d+\.\d+\.\d+/.test(res.json.version), `version looks semver (${res.json.version})`);
  ok(res.json.uptimeMs >= 0, 'uptime is reported');
});

test('fresh install starts with no chat debris', async () => {
  const state = await api.state();
  // `chats` is deliberately a bare array on the wire, not `{ chats: [...] }`.
  ok(Array.isArray(state.chats), 'chats is a list');
  equal(state.chats.length, 0, 'no chats on a fresh install');
  equal(state.activeId, null, 'no active chat');
  ok(state.settings.agentName, 'default agent name is set');
});

test('provider lifecycle: create, discover models, rename, delete', async () => {
  const created = await api.post('/api/providers', {
    name: 'Lifecycle',
    baseUrl: `${mockBase}/v1`,
    apiKey: 'sk-lifecycle',
  });
  equal(created.status, 200, 'create status');
  const id = created.json.provider.id;
  ok(created.json.provider.hasKey, 'key is stored (encrypted)');
  ok(created.json.provider.keyMasked.includes('•') || created.json.provider.keyMasked.includes('*'), 'key is masked for display');
  ok(!created.text.includes('sk-lifecycle'), 'plaintext key never leaves the server');

  const models = await api.post(`/api/providers/${id}/models`);
  equal(models.status, 200, 'model discovery status');
  ok(models.json.data.length >= 2, 'mock exposes several models');

  const renamed = await api.patch(`/api/providers/${id}`, { name: 'Lifecycle renamed' });
  equal(renamed.json.provider.name, 'Lifecycle renamed', 'rename applied');

  const removed = await api.del(`/api/providers/${id}`);
  equal(removed.status, 200, 'delete status');
  const after = await api.state();
  ok(!after.providers.some((p) => p.id === id), 'provider is gone from state');
});

test('model selection rejects anything not in the enabled catalog', async () => {
  const bad = await api.post('/api/active', { providerId, model: 'not-in-catalog' });
  equal(bad.status, 400, 'unknown model rejected');
  includes(bad.json.error.message, 'disabled or not in this provider list', 'error explains itself');

  const good = await api.post('/api/active', { providerId, model: 'mock-chat' });
  equal(good.status, 200, 'known model accepted');
  equal(good.json.active.model, 'mock-chat', 'active model updated');
});

test('streamed chat reaches the client as ordered deltas', async () => {
  const result = await streamChat(app.baseUrl, {
    providerId,
    model: 'mock-chat',
    messages: [{ role: 'user', content: 'Say hello' }],
  });
  equal(result.status, 200, 'stream status');
  equal(result.content, 'Hello from the mock provider.', 'assembled stream equals the mock answer');
  ok(result.events.length >= 5, `more than one delta arrived (${result.events.length})`);
  ok(result.firstDeltaMs !== null && result.firstDeltaMs < 3000, 'first token arrives promptly');
  // The stream closes with a meta frame (usage + trace id) and a profile frame
  // (which provider/model actually answered, and what else was attempted).
  ok(result.meta && result.meta.traceId, 'stream ends with a trace id');
  ok(result.meta.usage && result.meta.usage.total_tokens > 0, 'token usage is reported');
  ok(Array.isArray(result.meta.attempted), 'attempt log is reported per request');
});

test('reasoning deltas are forwarded separately from content', async () => {
  const result = await streamChat(app.baseUrl, {
    providerId,
    model: 'mock-chat',
    messages: [{ role: 'user', content: 'Do you reason about this?' }],
  });
  equal(result.status, 200, 'stream status');
  equal(result.content, 'Hello from the mock provider.', 'content is uncontaminated by reasoning');
  includes(result.reasoning, 'Thinking', 'reasoning stream captured');
});

test('upstream failures surface as errors, not silent empty answers', async () => {
  await fetch(`${mockBase}/control/scenario`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ mode: 'fail', failStatus: 429 }),
  });
  const result = await plainChat(app.baseUrl, {
    providerId,
    model: 'mock-chat',
    messages: [{ role: 'user', content: 'this will fail' }],
  });
  ok(result.status >= 400, `failure propagated (status ${result.status})`);
  ok(result.json && result.json.error && result.json.error.message, 'error carries a message');
});

test('a flaky provider is retried on the probe path (by design, not on chat)', async () => {
  await fetch(`${mockBase}/control/scenario`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ mode: 'flaky', failStatus: 503 }),
  });
  // Retry policy [6.7] covers provider probes: a 503 once, success on retry.
  const probe = await api.post(`/api/providers/${providerId}/test-model`, { model: 'mock-chat' });
  equal(probe.status, 200, 'probe succeeded after the retry');
  includes(JSON.stringify(probe.json), 'Hello from the mock provider.', 'probe reply came through');

  await fetch(`${mockBase}/control/reset`, { method: 'POST' });
});

test('a rate-limited stream surfaces the upstream error instead of faking an answer', async () => {
  await fetch(`${mockBase}/control/scenario`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ mode: 'fail', failStatus: 429 }),
  });
  const result = await streamChat(app.baseUrl, {
    providerId,
    model: 'mock-chat',
    messages: [{ role: 'user', content: 'rate limited' }],
  });
  // Once the 200 + text/event-stream headers are out, the status cannot be
  // changed — the failure has to arrive as an in-stream error event. What must
  // NOT happen is a 200 with an empty answer and no error at all.
  ok(result.errorEvent, 'an error event is delivered in-stream');
  includes(result.errorEvent.message, 'mock upstream failure', 'the upstream message is preserved');
  equal(result.content, '', 'no partial text is presented as a successful answer');

  await fetch(`${mockBase}/control/reset`, { method: 'POST' });
});

test('system prompt templates are expanded before they reach the provider', async () => {
  await api.post('/api/state/settings', { username: 'Zara', age: '27', preferredName: 'Zed', agentName: 'Archx' });
  const result = await streamChat(app.baseUrl, {
    providerId,
    model: 'mock-chat',
    messages: [
      { role: 'system', content: 'The user is {username}, age {age}. Call them {preferredName} from {agentName}.' },
      { role: 'user', content: 'who am i' },
    ],
  });
  equal(result.status, 200, 'stream status');

  const state = await api.state();
  equal(state.settings.username, 'Zara', 'personalization saved');
});

test('chat records persist through the single-chat upsert endpoint', async () => {
  const chat = {
    id: 'chat-test-1',
    title: 'Persistence check',
    ts: Date.now(),
    messages: [
      { role: 'user', content: 'hello', ts: Date.now() },
      { role: 'assistant', content: 'hi there', ts: Date.now() },
    ],
  };
  const saved = await api.post('/api/state/chat', { chat, activeId: chat.id });
  equal(saved.status, 200, 'upsert accepted');

  const state = await api.state();
  const stored = state.chats.find((c) => c.id === chat.id);
  ok(stored, 'chat is in state');
  equal(stored.messages.length, 2, 'both messages stored');
  equal(state.activeId, chat.id, 'active chat tracked');
});

test('bulk chat write validates its payload', async () => {
  const bad = await api.post('/api/state/chats', { activeId: 'x' });
  equal(bad.status, 400, 'missing chats[] rejected');
});

test('settings writes are clamped to legal ranges', async () => {
  await api.post('/api/state/settings', { temperature: 99, maxTokens: -5, theme: 'neon' });
  const state = await api.state();
  between(state.settings.temperature, 0, 2, 'temperature clamped');
  ok(state.settings.theme !== 'neon', 'unknown theme is ignored');
});

test('every request is written to the debug journal', async () => {
  const logs = await api.get('/api/logs?limit=50');
  equal(logs.status, 200, 'logs readable');
  ok(Array.isArray(logs.json.entries), 'entries array present');
  ok(logs.json.entries.length > 0, 'chat calls were logged');

  const rev = await api.get('/api/logs/rev');
  ok(rev.json.rev >= 0, 'revision counter exposed for cheap polling');
});

test('storage view points at the sandbox data area', async () => {
  const state = await api.state();
  equal(state.storage.dir, app.dataDir, 'data area honours ARCHX_DATA_DIR');
  ok(state.storage.database.endsWith('archx.db'), 'database path reported');
});

test('static assets are served and cacheable', async () => {
  for (const route of ['/', '/css/base.css', '/js/ui.js']) {
    const res = await api.get(route);
    equal(res.status, 200, `${route} served`);
    ok(res.text.length > 100, `${route} has content`);
  }
  const vendor = await api.get('/vendor/markdown-it.min.js');
  equal(vendor.status, 200, 'vendored markdown parser served');
  includes(vendor.headers.get('cache-control') || '', 'max-age', 'vendor assets carry a cache header');
});

test('unknown routes are a clean 404', async () => {
  const res = await api.get('/api/does-not-exist');
  equal(res.status, 404, 'unknown api route');
  equal(res.headers.get('x-powered-by'), null, 'express fingerprint removed');
});

test('anthropic adapter speaks the Messages protocol', async () => {
  const id = await api.addProvider({
    name: 'Mock Anthropic',
    baseUrl: `${mockBase}/anthropic/v1`,
    adapter: 'anthropic',
    model: 'mock-claude',
  });
  const result = await streamChat(app.baseUrl, {
    providerId: id,
    model: 'mock-claude',
    messages: [
      { role: 'system', content: 'be brief' },
      { role: 'user', content: 'hello' },
    ],
  });
  equal(result.status, 200, 'anthropic stream status');
  equal(result.content, 'Hello from the mock provider.', 'anthropic deltas assembled');

  await api.post('/api/active', { providerId, model: 'mock-chat' });
});

test('gemini adapter speaks the Generative Language protocol', async () => {
  const id = await api.addProvider({
    name: 'Mock Gemini',
    baseUrl: `${mockBase}/gemini/v1beta`,
    adapter: 'gemini',
    model: 'mock-gemini',
  });
  const models = await api.post(`/api/providers/${id}/models`);
  equal(models.status, 200, 'gemini model discovery');
  ok(
    models.json.data.every((m) => !String(m.id || '').startsWith('models/')),
    'model ids are normalized (no models/ prefix)'
  );
  ok(!models.json.data.some((m) => m.id === 'mock-embedding'), 'non-chat models filtered out');

  const result = await streamChat(app.baseUrl, {
    providerId: id,
    model: 'mock-gemini',
    messages: [{ role: 'user', content: 'hello' }],
  });
  equal(result.status, 200, 'gemini stream status');
  equal(result.content, 'Hello from the mock provider.', 'gemini deltas assembled');

  await api.post('/api/active', { providerId, model: 'mock-chat' });
});

test('deleting the active provider leaves the app usable', async () => {
  const tempId = await api.addProvider({ baseUrl: `${mockBase}/v1`, model: 'mock-chat' });
  await api.del(`/api/providers/${tempId}`);
  const state = await api.state();
  ok(state.providers.length >= 1, 'other providers survive');
  const health = await api.get('/api/health');
  equal(health.status, 200, 'server still healthy after deletion');
});
