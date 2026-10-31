'use strict';

/*
 * Google Gemini native provider adapter (Generative Language API).
 * Wire protocol: REST + SSE (`alt=sse`) against
 *   {base}/models                     → model discovery
 *   {base}/models/{model}:generateContent          → one-shot
 *   {base}/models/{model}:streamGenerateContent?alt=sse → streaming
 * Auth: `x-goog-api-key` header (or ?key= — we use the header).
 * Default base: https://generativelanguage.googleapis.com/v1beta
 * Thinking models surface reasoning via parts flagged `thought: true`.
 */

const { ProxyError } = require('./proxy-error.js');

const DEFAULT_BASE = 'https://generativelanguage.googleapis.com/v1beta';

function baseOf(baseUrl) {
  let raw = String(baseUrl || '').trim().replace(/\/+$/, '');
  if (!raw) return DEFAULT_BASE;
  if (!/^https?:\/\//i.test(raw)) raw = 'https://' + raw;
  let u;
  try {
    u = new URL(raw);
  } catch {
    throw new ProxyError(`"${baseUrl}" is not a valid URL.`, 400);
  }
  // Accept "…/v1beta", "…/v1" or a bare host; also tolerate OpenAI-style /v1 paths
  // by mapping them onto the Gemini versioned root when obviously intended.
  if (!u.pathname || u.pathname === '/') u.pathname = '/v1beta';
  return u.toString().replace(/\/+$/, '');
}

function headersFor(apiKey) {
  const h = { 'Content-Type': 'application/json', Accept: 'application/json' };
  if (apiKey) h['x-goog-api-key'] = apiKey;
  return h;
}

async function readErrorBody(res) {
  let body = null;
  try {
    const text = await res.text();
    try { body = JSON.parse(text); } catch { body = text ? text.slice(0, 2000) : null; }
  } catch { /* ignore */ }
  const msg =
    (body && body.error && (body.error.message || body.error.status)) ||
    (typeof body === 'string' ? body : null);
  return { msg: typeof msg === 'string' ? msg : null, body };
}

function composeTimeout(signal, ms) {
  if (!ms) return signal;
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(new Error('timeout')), ms);
  if (signal) {
    if (signal.aborted) ctrl.abort(signal.reason);
    else signal.addEventListener('abort', () => ctrl.abort(signal.reason), { once: true });
  }
  ctrl.signal.addEventListener('abort', () => clearTimeout(t), { once: true });
  return ctrl.signal;
}

function networkError(err, base) {
  if (err && err.name === 'AbortError') return new ProxyError('Request timed out.', 504);
  const cause = err && err.cause ? err.cause.code || err.cause.message : err && err.code;
  const hint =
    cause === 'ECONNREFUSED' ? 'Connection refused — is the endpoint running and reachable from this machine?' :
    cause === 'ENOTFOUND' || cause === 'EAI_AGAIN' ? 'Hostname could not be resolved — check the base URL.' :
    `Network error${cause ? ` (${cause})` : ''}.`;
  return new ProxyError(`${hint} [${base}]`, 502, String((err && err.message) || err));
}

/** Model ids may arrive as "models/gemini-…" or bare; normalize to bare. */
const bareId = (id) => String(id || '').replace(/^models\//, '');

async function listModels({ baseUrl, apiKey, timeoutMs = 20000, signal } = {}) {
  const base = baseOf(baseUrl);
  let res;
  let pageToken = null;
  const out = [];
  do {
    const url = `${base}/models?pageSize=200${pageToken ? `&pageToken=${encodeURIComponent(pageToken)}` : ''}`;
    try {
      res = await fetch(url, { headers: headersFor(apiKey), signal: composeTimeout(signal, timeoutMs) });
    } catch (err) {
      throw networkError(err, base);
    }
    if (!res.ok) {
      const { msg, body } = await readErrorBody(res);
      throw new ProxyError(msg || `The provider answered ${res.status} ${res.statusText || ''} on /models.`, res.status, body);
    }
    const json = await res.json().catch(() => null);
    const list = Array.isArray(json && json.models) ? json.models : null;
    if (!list) throw new ProxyError('Provider returned an unexpected /models payload.', 502, json);
    for (const m of list) {
      const id = bareId(m && m.name);
      if (!id) continue;
      // Only chat-capable models belong in the picker.
      const methods = Array.isArray(m && m.supportedGenerationMethods) ? m.supportedGenerationMethods : [];
      if (methods.length && !methods.includes('generateContent')) continue;
      out.push({ id, owned_by: (m && m.ownedBy) || 'google', displayName: (m && m.displayName) || undefined });
    }
    pageToken = json && json.nextPageToken ? json.nextPageToken : null;
  } while (pageToken);
  return out.sort((a, b) => a.id.localeCompare(b.id));
}

/* 1.8.0: content may be a string or an OpenAI-style part array
   [{type:'text',text},{type:'image_url',image_url:{url:'data:mime;base64,..'}}]. */
function contentToParts(content) {
  if (typeof content === 'string') return [{ text: content }];
  if (Array.isArray(content)) {
    const parts = [];
    for (const p of content) {
      if (!p) continue;
      if (p.type === 'text' && typeof p.text === 'string') parts.push({ text: p.text });
      else if (p.type === 'image_url' && typeof p.image_url?.url === 'string' && p.image_url.url.startsWith('data:')) {
        const m = /^data:([^;]+);base64,(.+)$/.exec(p.image_url.url);
        if (m) parts.push({ inline_data: { mime_type: m[1], data: m[2] } });
      } else if (p.type === 'input_audio' && p.input_audio?.data) {
        parts.push({ inline_data: { mime_type: p.input_audio.mime || 'audio/mpeg', data: p.input_audio.data } });
      }
    }
    return parts.length ? parts : [{ text: '' }];
  }
  return [{ text: String(content ?? '') }];
}

/** OpenAI-style messages → Gemini {systemInstruction, contents}. */
function convertMessages(messages) {
  const system = [];
  const contents = [];
  for (const m of Array.isArray(messages) ? messages : []) {
    if (!m) continue;
    if (m.role === 'system') {
      if (typeof m.content === 'string') system.push(m.content);
      else system.push(...contentToParts(m.content).filter((p) => p.text).map((p) => p.text));
      continue;
    }
    const role = m.role === 'assistant' ? 'model' : 'user';
    const parts = contentToParts(m.content);
    const last = contents[contents.length - 1];
    if (last && last.role === role) last.parts.push(...parts);
    else contents.push({ role, parts });
  }
  return {
    systemInstruction: system.length ? { parts: system.map((text) => ({ text })) } : undefined,
    contents,
  };
}

function generationConfig(opts) {
  const cfg = {};
  if (typeof opts.temperature === 'number' && !Number.isNaN(opts.temperature)) cfg.temperature = opts.temperature;
  if (Number(opts.maxTokens) > 0) cfg.maxOutputTokens = Number(opts.maxTokens);
  return Object.keys(cfg).length ? cfg : undefined;
}

function usageOf(meta) {
  if (!meta) return null;
  const prompt = meta.promptTokenCount;
  const completion = meta.candidatesTokenCount;
  if (prompt == null && completion == null) return null;
  return {
    prompt_tokens: prompt || 0,
    completion_tokens: completion || 0,
    total_tokens: meta.totalTokenCount != null ? meta.totalTokenCount : (prompt || 0) + (completion || 0),
  };
}

function extractParts(json, cb) {
  let text = '';
  let reasoning = '';
  const candidate = json && json.candidates && json.candidates[0];
  const parts = (candidate && candidate.content && candidate.content.parts) || [];
  for (const part of parts) {
    if (!part || typeof part.text !== 'string' || !part.text) continue;
    if (part.thought === true) reasoning += part.text;
    else text += part.text;
  }
  return { text, reasoning };
}

async function chatCompletion(opts, cb = {}) {
  const base = baseOf(opts.baseUrl);
  const { systemInstruction, contents } = convertMessages(opts.messages);
  if (!contents.length) throw new ProxyError('Gemini requires at least one user message.', 400);
  const body = { contents };
  if (systemInstruction) body.systemInstruction = systemInstruction;
  const cfg = generationConfig(opts);
  if (cfg) body.generationConfig = cfg;

  const model = encodeURIComponent(String(opts.model || ''));
  const url = opts.stream
    ? `${base}/models/${model}:streamGenerateContent?alt=sse`
    : `${base}/models/${model}:generateContent`;

  let res;
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: headersFor(opts.apiKey),
      body: JSON.stringify(body),
      signal: composeTimeout(opts.signal, opts.timeoutMs || 0),
    });
  } catch (err) {
    throw networkError(err, base);
  }
  if (!res.ok) {
    const { msg, body: eb } = await readErrorBody(res);
    throw new ProxyError(msg || `The provider answered ${res.status} ${res.statusText || ''}.`, res.status, eb);
  }

  if (!opts.stream) {
    const json = await res.json().catch(() => null);
    if (!json) throw new ProxyError('Provider returned an empty response.', 502);
    const { text, reasoning } = extractParts(json);
    const usage = usageOf(json.usageMetadata);
    if (cb.onMeta) cb.onMeta({ usage, model: json.modelVersion || opts.model });
    if (reasoning && cb.onReasoning) cb.onReasoning(reasoning);
    return { text, reasoning, model: json.modelVersion || opts.model, usage };
  }

  if (!res.body) throw new ProxyError('Provider returned an empty streaming body.', 502);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let full = '';
  let fullReasoning = '';
  let usage = null;
  let respModel = null;

  const handleChunk = (j) => {
    if (!j || typeof j !== 'object') return;
    if (j.error) throw new ProxyError(j.error.message || 'Provider stream error.', 502, j.error);
    const { text, reasoning } = extractParts(j);
    if (text) { full += text; if (cb.onDelta) cb.onDelta(text); }
    if (reasoning) { fullReasoning += reasoning; if (cb.onReasoning) cb.onReasoning(reasoning); }
    if (j.usageMetadata) usage = usageOf(j.usageMetadata) || usage;
    if (j.modelVersion) respModel = j.modelVersion;
  };

  const handleLine = (line) => {
    const trimmed = line.trim();
    if (!trimmed.startsWith('data:')) return;
    const payload = trimmed.slice(5).trim();
    if (!payload || payload === '[DONE]') return;
    let j;
    try { j = JSON.parse(payload); } catch { return; }
    handleChunk(j);
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl);
      buf = buf.slice(nl + 1);
      handleLine(line);
    }
  }
  if (buf.trim()) handleLine(buf);
  if (cb.onMeta) cb.onMeta({ usage, model: respModel || opts.model });
  return { text: full, reasoning: fullReasoning, model: respModel || opts.model, usage };
}

/* ── image generation (1.8.0) — generateContent with IMAGE modality ── */
async function generateImage({ baseUrl, apiKey, model, prompt, image, imageMime, timeoutMs = 90000 }) {
  const base = baseOf(baseUrl);
  const parts = [{ text: prompt }];
  if (image) parts.push({ inline_data: { mime_type: imageMime || 'image/png', data: image } });
  const body = {
    contents: [{ role: 'user', parts }],
    generationConfig: { responseModalities: ['TEXT', 'IMAGE'] },
  };
  const url = `${base}/models/${encodeURIComponent(String(model || ''))}:generateContent`;
  let res;
  try {
    res = await fetch(url, { method: 'POST', headers: headersFor(apiKey), body: JSON.stringify(body), signal: composeTimeout(null, timeoutMs) });
  } catch (err) { throw networkError(err, base); }
  if (!res.ok) {
    const { msg, body: eb } = await readErrorBody(res);
    throw new ProxyError(msg || `The provider answered ${res.status} on :generateContent.`, res.status, eb);
  }
  const json = await res.json().catch(() => null);
  const candidate = json && json.candidates && json.candidates[0];
  const outParts = (candidate && candidate.content && candidate.content.parts) || [];
  let text = '';
  let imageData = null;
  let mime = 'image/png';
  for (const p of outParts) {
    if (!p) continue;
    if (typeof p.text === 'string' && p.thought !== true) text += p.text;
    if (p.inlineData && p.inlineData.data) { imageData = p.inlineData.data; mime = p.inlineData.mimeType || mime; }
  }
  if (!imageData) throw new ProxyError(text ? `Model answered with text but no image: ${text.slice(0, 200)}` : 'Model returned no image data.', 502, json);
  return { base64: imageData, mime, revisedPrompt: text || null };
}

/* ── text → speech (1.8.0) — generateContent with AUDIO modality ── */
async function speech({ baseUrl, apiKey, model, input, voice, timeoutMs = 90000 }) {
  const base = baseOf(baseUrl);
  const body = {
    contents: [{ role: 'user', parts: [{ text: input }] }],
    generationConfig: {
      responseModalities: ['AUDIO'],
      speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName: voice || 'Kore' } } },
    },
  };
  const url = `${base}/models/${encodeURIComponent(String(model || ''))}:generateContent`;
  let res;
  try {
    res = await fetch(url, { method: 'POST', headers: headersFor(apiKey), body: JSON.stringify(body), signal: composeTimeout(null, timeoutMs) });
  } catch (err) { throw networkError(err, base); }
  if (!res.ok) {
    const { msg, body: eb } = await readErrorBody(res);
    throw new ProxyError(msg || `The provider answered ${res.status} on :generateContent (audio).`, res.status, eb);
  }
  const json = await res.json().catch(() => null);
  const parts = (json && json.candidates && json.candidates[0] && json.candidates[0].content && json.candidates[0].content.parts) || [];
  const audio = parts.find((p) => p && p.inlineData && p.inlineData.data);
  if (!audio) throw new ProxyError('Model returned no audio data.', 502, json);
  return { base64: audio.inlineData.data, mime: audio.inlineData.mimeType || 'audio/wav' };
}

/* ── speech → text (1.8.0) — audio inline_data + instruction ── */
async function transcribe({ baseUrl, apiKey, model, audio, mime = 'audio/mpeg', timeoutMs = 90000 }) {
  const base = baseOf(baseUrl);
  const body = {
    contents: [{ role: 'user', parts: [{ inline_data: { mime_type: mime, data: audio } }, { text: 'Transcribe this audio verbatim. Output only the transcription.' }] }],
  };
  const url = `${base}/models/${encodeURIComponent(String(model || ''))}:generateContent`;
  let res;
  try {
    res = await fetch(url, { method: 'POST', headers: headersFor(apiKey), body: JSON.stringify(body), signal: composeTimeout(null, timeoutMs) });
  } catch (err) { throw networkError(err, base); }
  if (!res.ok) {
    const { msg, body: eb } = await readErrorBody(res);
    throw new ProxyError(msg || `The provider answered ${res.status} on :generateContent (transcribe).`, res.status, eb);
  }
  const json = await res.json().catch(() => null);
  const { text } = extractParts(json, {});
  return { text };
}

module.exports = { listModels, chatCompletion, generateImage, speech, transcribe, DEFAULT_BASE };
