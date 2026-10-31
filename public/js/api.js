/* Archx Agent — server API wrappers (v2) */

import { readChatStream } from './chat-events.mjs';

const j = (r) => r.json().catch(() => null);

async function errFrom(res, fallback) {
  const body = await j(res);
  return new Error((body && body.error && body.error.message) || fallback || `HTTP ${res.status}`);
}

const post = (url, body) =>
  fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

export async function getState() {
  const res = await fetch('/api/state');
  if (!res.ok) throw await errFrom(res);
  return res.json();
}

export async function setSettings(patch) {
  const res = await post('/api/state/settings', patch);
  if (!res.ok) throw await errFrom(res);
  return (await res.json()).settings;
}

export async function setChats(chats, activeId) {
  const res = await post('/api/state/chats', { chats, activeId });
  if (!res.ok) throw await errFrom(res);
  return true;
}

/* single-chat upsert (streaming hot path) */
export async function setChat(chat, activeId) {
  const res = await post('/api/state/chat', { chat, activeId });
  if (!res.ok) throw await errFrom(res);
  return true;
}

/* ---- providers ---- */
export async function addProvider({ name, baseUrl, apiKey, adapter }) {
  const res = await post('/api/providers', { name, baseUrl, apiKey, adapter });
  const body = await j(res);
  if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`);
  return body;
}

export async function patchProvider(id, patch) {
  const res = await fetch(`/api/providers/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  const body = await j(res);
  if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`);
  return body;
}

export async function deleteProvider(id, modelPolicy = 'pause') {
  const res = await fetch(`/api/providers/${id}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ modelPolicy }),
  });
  const body = await j(res);
  if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`);
  return body;
}

/* ---- studio (1.8.0) ---- */
export async function generateImage(id, { model, prompt, image, imageMime } = {}) {
  const res = await post(`/api/providers/${id}/generate-image`, { model, prompt, image, imageMime });
  const body = await j(res);
  if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`);
  return body;
}
export async function speech(id, { model, input, voice } = {}) {
  const res = await post(`/api/providers/${id}/speech`, { model, input, voice });
  const body = await j(res);
  if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`);
  return body;
}
export async function transcribe(id, { model, audio, mime } = {}) {
  const res = await post(`/api/providers/${id}/transcribe`, { model, audio, mime });
  const body = await j(res);
  if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`);
  return body;
}
export async function testModelLive(id, { model, silent, attempts, message, prompt, input } = {}) {
  const res = await post(`/api/providers/${id}/test-model`, { model, silent, attempts, message, prompt, input });
  const body = await j(res);
  if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`);
  return body;
}
export async function logBatchTest(id, { results, stopped } = {}) {
  const res = await post(`/api/providers/${id}/test-batch-log`, { results, stopped });
  return res.ok;
}
export async function webSearchTest() {
  const res = await fetch('/api/tools/web-search/test');
  if (!res.ok) throw await errFrom(res);
  return res.json();
}
export async function memoryStats() {
  const res = await fetch('/api/memory-stats');
  if (!res.ok) throw await errFrom(res);
  return res.json();
}

export async function addModelProfile({ name, providerId, models, items } = {}) {
  const res = await post('/api/profiles', { name, providerId, models, items });
  const body = await j(res); if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`); return body;
}

export async function patchModelProfile(id, patch) {
  const res = await fetch(`/api/profiles/${id}`, { method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify(patch) });
  const body = await j(res); if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`); return body;
}

export async function deleteModelProfile(id) {
  const res = await fetch(`/api/profiles/${id}`, { method:'DELETE' });
  const body = await j(res); if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`); return body;
}

export async function setActiveProfile(profileId) {
  const res = await post('/api/active-profile', { profileId });
  const body = await j(res); if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`); return body;
}

export async function setActive({ providerId, model } = {}) {
  const res = await post('/api/active', { providerId, model });
  const body = await j(res);
  if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`);
  return body.active;
}


export async function testProviderDraft({ baseUrl, apiKey, adapter } = {}) {
  const res = await post('/api/provider-test', { baseUrl, apiKey, adapter });
  const body = await j(res);
  if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`);
  return body;
}

export async function testProvider(id) {
  const res = await post(`/api/providers/${id}/test`, {});
  const body = await j(res);
  if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`);
  return body;
}

export async function testModel(id, model, message) {
  const res = await post(`/api/providers/${id}/test-model`, { model, message });
  const body = await j(res);
  if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`);
  return body;
}


export async function testAllModels(id, message, concurrency = 4) {
  const res = await post(`/api/providers/${id}/test-all`, { message, concurrency });
  const body = await j(res);
  if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`);
  return body;
}

/* Batch-probe arbitrary model ids (used by the add-models dialog).
   The server gives each model two attempts by default. */
export async function testModels(id, models, { message, concurrency = 4, attempts = 2 } = {}) {
  const res = await post(`/api/providers/${id}/test-models`, { models, message, concurrency, attempts });
  const body = await j(res);
  if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`);
  return body;
}

export async function deleteProviderModels(id, models) {
  const res = await post(`/api/providers/${id}/delete-models`, { models });
  const body = await j(res);
  if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`);
  return body;
}

export async function deleteProviderModel(id, model) {
  const res = await post(`/api/providers/${id}/delete-model`, { model });
  const body = await j(res);
  if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`);
  return body;
}
export async function getProviderModels(id) {
  const res = await post(`/api/providers/${id}/models`, {});
  const body = await j(res);
  if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`);
  return body || { data: [] };
}

/* ---- logs (debug page) ---- */
export async function getChatDebug({ traceIds = [], chatId = null, limit = 600 } = {}) {
  const params = new URLSearchParams();
  if (traceIds.length) params.set('traceIds', traceIds.join(','));
  if (chatId) params.set('chatId', chatId);
  params.set('limit', String(limit));
  const res = await fetch(`/api/chat-debug?${params.toString()}`);
  if (!res.ok) throw await errFrom(res, 'Chat debug unavailable');
  return res.json();
}

export async function getLogs(limit = 500) {
  const res = await fetch(`/api/logs?limit=${limit}`);
  if (!res.ok) throw await errFrom(res);
  return res.json();
}

/* cheap journal revision probe for pollers */
export async function getLogsRev() {
  const res = await fetch('/api/logs/rev');
  if (!res.ok) throw await errFrom(res);
  return res.json();
}

export async function clearLogs() {
  const res = await fetch('/api/logs', { method: 'DELETE' });
  if (!res.ok) throw await errFrom(res);
  return true;
}

/* ---- storage ---- */
export async function setStorage(dir) {
  const res = await post('/api/storage', { dir });
  const body = await j(res);
  if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`);
  return body;
}

export async function wipe(scope = 'all') {
  const res = await post('/api/wipe', { scope });
  if (!res.ok) throw await errFrom(res);
  return true;
}

/* ---- chat ----
 * The server injects the decrypted key for the chosen provider.
 * cb: onDelta(text), onReasoning(text), onMeta(obj)
 */
export async function chat({ providerId, model, messages, stream, temperature, maxTokens, profileId, chatId, systemPromptId, modeId, useWebSearch }, signal, cb = {}) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
    body: JSON.stringify({ providerId, model, messages, stream, temperature, maxTokens, profileId, chatId, systemPromptId, modeId, useWebSearch }),
  });

  if (!stream) {
    const body = await j(res);
    if (!res.ok) throw new Error((body && body.error && body.error.message) || `HTTP ${res.status}`);
    if (cb.onMeta) cb.onMeta(body);
    if (Array.isArray(body.tools) && cb.onTool) body.tools.forEach(cb.onTool);
    const message = body.choices && body.choices[0] && body.choices[0].message;
    if (message && message.reasoning_content && cb.onReasoning) cb.onReasoning(message.reasoning_content);
    return (message && message.content) || '';
  }

  const ctype = res.headers.get('content-type') || '';
  if (!res.ok && !ctype.includes('text/event-stream')) throw await errFrom(res);
  if (!res.body) throw new Error('Empty streaming response.');

  return readChatStream(res.body, cb);
}
