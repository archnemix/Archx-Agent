'use strict';

const { normalizeBaseUrl } = require('../util.js');
const { ProxyError } = require('./proxy-error.js');
/* 1.9.0: official OpenAI client for the tool surfaces (speech / transcription /
   images) so multipart bodies, filenames and error shapes are exactly the
   OpenAI wire format every compatible host (Groq, NIM, Mistral, OpenRouter…)
   expects. Chat stays on the streaming fetch passthrough. */
let OpenAICtor = null, toFile = null;
try { ({ OpenAI: OpenAICtor, toFile } = require('openai')); } catch { /* optional */ }

const MIME_EXT = { 'audio/mpeg': 'mp3', 'audio/mp3': 'mp3', 'audio/flac': 'flac', 'audio/x-flac': 'flac', 'audio/mp4': 'mp4', 'audio/x-mp4': 'mp4', 'audio/mpeg4': 'mp4', 'audio/mpga': 'mpga', 'audio/x-m4a': 'm4a', 'audio/m4a': 'm4a', 'audio/ogg': 'ogg', 'audio/opus': 'opus', 'audio/wav': 'wav', 'audio/x-wav': 'wav', 'audio/wave': 'wav', 'audio/webm': 'webm' };
const extForMime = (mime) => MIME_EXT[String(mime || '').toLowerCase()] || (String(mime || '').split('/')[1] || 'mp3').replace(/[^a-z0-9]/g, '') || 'mp3';
function openaiClient(base, apiKey, timeoutMs) {
  if (!OpenAICtor) return null;
  return new OpenAICtor({ apiKey: apiKey || 'none', baseURL: base, maxRetries: 0, timeout: timeoutMs || 60000 });
}
const sdkError = (err, fallbackStatus) => {
  const status = Number(err?.status) || fallbackStatus || 502;
  const msg = err?.error?.message || err?.message || 'Provider request failed.';
  return new ProxyError(msg, status, err?.error || null);
};

function headersFor(apiKey) {
  const h = { 'Content-Type': 'application/json', Accept: 'application/json' };
  if (apiKey) h.Authorization = `Bearer ${apiKey}`;
  return h;
}

async function readErrorBody(res) {
  let body = null;
  try {
    const text = await res.text();
    try { body = JSON.parse(text); } catch { body = text ? text.slice(0, 2000) : null; }
  } catch { /* ignore */ }
  const msg = (body && body.error && (body.error.message || body.error)) || (typeof body === 'string' ? body : null);
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
    cause === 'CERT_HAS_EXPIRED' || cause === 'UNABLE_TO_VERIFY_LEAF_SIGNATURE' || cause === 'SELF_SIGNED_CERT_IN_CHAIN' ? 'TLS certificate problem (self-signed local endpoints may need NODE_EXTRA_CA_CERTS).' :
    cause === 'ECONNRESET' ? 'Connection reset by the provider.' :
    `Network error${cause ? ` (${cause})` : ''}.`;
  return new ProxyError(`${hint} [${base}]`, 502, String((err && err.message) || err));
}

async function listModels({ baseUrl, apiKey, timeoutMs = 20000, signal } = {}) {
  const base = normalizeBaseUrl(baseUrl);
  let res;
  try {
    res = await fetch(`${base}/models`, { headers: headersFor(apiKey), signal: composeTimeout(signal, timeoutMs) });
  } catch (err) {
    throw networkError(err, base);
  }
  if (!res.ok) {
    const { msg, body } = await readErrorBody(res);
    throw new ProxyError(msg || `The provider answered ${res.status} ${res.statusText || ''} on /models.`, res.status, body);
  }
  const json = await res.json().catch(() => null);
  let list = Array.isArray(json) ? json : Array.isArray(json && json.data) ? json.data : null;
  if (!list) throw new ProxyError('Provider returned an unexpected /models payload.', 502, json);
  return list
    .map((m) => (typeof m === 'string' ? { id: m } : m))
    .filter((m) => m && typeof m.id === 'string' && m.id.length)
    .sort((a, b) => a.id.localeCompare(b.id));
}

async function chatCompletion(opts, cb = {}) {
  const base = normalizeBaseUrl(opts.baseUrl);
  const body = { model: opts.model, messages: opts.messages, stream: !!opts.stream };
  if (typeof opts.temperature === 'number' && !Number.isNaN(opts.temperature)) body.temperature = opts.temperature;
  if (opts.maxTokens) body.max_tokens = opts.maxTokens;

  let res;
  try {
    res = await fetch(`${base}/chat/completions`, {
      method: 'POST', headers: headersFor(opts.apiKey), body: JSON.stringify(body),
      signal: composeTimeout(opts.signal, opts.timeoutMs || 0),
    });
  } catch (err) {
    throw networkError(err, base);
  }

  if (!res.ok) {
    const { msg, body: eb } = await readErrorBody(res);
    throw new ProxyError(msg || `The provider answered ${res.status} ${res.statusText || ''} on /chat/completions.`, res.status, eb);
  }

  if (!opts.stream) {
    const json = await res.json().catch(() => null);
    const message = json && json.choices && json.choices[0] && json.choices[0].message;
    const text = message ? message.content || '' : '';
    const reasoning = message ? message.reasoning_content || message.reasoning || message.thinking || '' : '';
    if (cb.onMeta) cb.onMeta({ usage: json && json.usage, model: json && json.model });
    if (reasoning && cb.onReasoning) cb.onReasoning(reasoning);
    return { text, reasoning };
  }

  if (!res.body) throw new ProxyError('Provider returned an empty streaming body.', 502);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let full = '';
  let fullReasoning = '';
  let usage = null;
  let respModel = null;
  let completed = false;

  const handleLine = (line) => {
    const trimmed = line.trim();
    if (!trimmed.startsWith('data:')) return;
    const payload = trimmed.slice(5).trim();
    if (!payload) return;
    if (payload === '[DONE]') { completed = true; return; }
    let j;
    try { j = JSON.parse(payload); } catch { return; }
    if (j.error) throw new ProxyError(j.error.message || 'Provider stream error.', 502, j.error);
    if (j.model) respModel = j.model;
    if (j.usage) usage = j.usage;
    const choice = j.choices && j.choices[0];
    if (!choice) return;
    if (choice.finish_reason != null) completed = true;
    const delta = choice.delta && typeof choice.delta.content === 'string' ? choice.delta.content : null;
    const text = delta !== null ? delta : typeof choice.text === 'string' ? choice.text : null;
    if (text) { full += text; if (cb.onDelta) cb.onDelta(text); }
    const dlt = choice.delta || {};
    const reason = typeof dlt.reasoning_content === 'string' ? dlt.reasoning_content : typeof dlt.reasoning === 'string' ? dlt.reasoning : typeof dlt.thinking === 'string' ? dlt.thinking : null;
    if (reason) { fullReasoning += reason; if (cb.onReasoning) cb.onReasoning(reason); }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl); buf = buf.slice(nl + 1); handleLine(line);
    }
  }
  if (buf.trim()) handleLine(buf);
  if (!completed) throw new ProxyError('Upstream completion is unconfirmed: the provider stream ended before a completion marker.', 502);
  if (cb.onMeta) cb.onMeta({ usage, model: respModel });
  return { text: full, reasoning: fullReasoning };
}

/* ── image generation (1.8.0) ───────────────────────────────────
 * OpenAI-style /images/generations. A reference image (base64) is sent as an
 * `image` field for providers that support edits-through-generations; it is
 * ignored by providers that only accept a prompt. */
async function generateImage({ baseUrl, apiKey, model, prompt, image, imageMime, timeoutMs = 60000 }) {
  const base = normalizeBaseUrl(baseUrl);
  const body = { model, prompt, n: 1 };
  if (image) body.image = `data:${imageMime || 'image/png'};base64,${image}`;
  let res;
  try {
    res = await fetch(`${base}/images/generations`, { method: 'POST', headers: headersFor(apiKey), body: JSON.stringify(body), signal: composeTimeout(null, timeoutMs) });
  } catch (err) { throw networkError(err, base); }
  if (!res.ok) {
    const { msg, body: eb } = await readErrorBody(res);
    throw new ProxyError(msg || `The provider answered ${res.status} on /images/generations.`, res.status, eb);
  }
  const json = await res.json().catch(() => null);
  const item = json && Array.isArray(json.data) && json.data[0];
  if (!item) throw new ProxyError('Provider returned no image data.', 502, json);
  if (item.b64_json) return { base64: item.b64_json, mime: 'image/png', revisedPrompt: item.revised_prompt || null };
  if (item.url) {
    const img = await fetch(item.url, { signal: composeTimeout(null, timeoutMs) });
    if (!img.ok) throw new ProxyError(`Image URL answered ${img.status}.`, 502);
    const buf = Buffer.from(await img.arrayBuffer());
    const mime = img.headers.get('content-type') || 'image/png';
    return { base64: buf.toString('base64'), mime, revisedPrompt: item.revised_prompt || null, sourceUrl: item.url };
  }
  throw new ProxyError('Provider returned an unsupported image payload.', 502, json);
}

/* ── text → speech (1.9.0: OpenAI client + provider voice discovery) ── */
const voiceCache = new Map(); // baseUrl → first usable voice slug (or null)

/** GET /audio/voices (Mistral-style catalog) → first usable voice slug, cached. */
async function discoverVoice(base, apiKey) {
  if (voiceCache.has(base)) return voiceCache.get(base);
  let pick = null;
  try {
    const res = await fetch(`${base}/audio/voices`, { headers: headersFor(apiKey), signal: composeTimeout(null, 10000) });
    if (res.ok) {
      const json = await res.json().catch(() => null);
      const items = Array.isArray(json?.items) ? json.items
        : Array.isArray(json?.voices) ? json.voices
          : Array.isArray(json?.data) ? json.data : [];
      const first = items[0];
      const v = typeof first === 'string' ? first : (first?.slug || first?.voice_id || first?.id || null);
      if (v) pick = String(v);
    }
  } catch { /* discovery is best-effort */ }
  voiceCache.set(base, pick);
  return pick;
}

async function speech({ baseUrl, apiKey, model, input, voice, timeoutMs = 60000 }) {
  const base = normalizeBaseUrl(baseUrl);
  let useVoice = voice || 'alloy';
  for (let attempt = 0; attempt < 2; attempt++) {
    const client = openaiClient(base, apiKey, timeoutMs);
    let ct = '', buf = null, json = null;
    try {
      if (client) {
        const res = await client.audio.speech.create({ model, input: String(input ?? ''), voice: useVoice });
        ct = String(res.headers?.get?.('content-type') || '');
        if (ct.includes('application/json')) json = await res.json();
        else buf = Buffer.from(await res.arrayBuffer());
      } else {
        const body = { model, input: String(input ?? ''), voice: useVoice };
        const res = await fetch(`${base}/audio/speech`, { method: 'POST', headers: headersFor(apiKey), body: JSON.stringify(body), signal: composeTimeout(null, timeoutMs) });
        ct = String(res.headers.get('content-type') || '');
        if (!res.ok) {
          const { msg, body: eb } = await readErrorBody(res);
          throw new ProxyError(msg || `The provider answered ${res.status} on /audio/speech.`, res.status, eb);
        }
        if (ct.includes('application/json')) json = await res.json().catch(() => null);
        else buf = Buffer.from(await res.arrayBuffer());
      }
    } catch (err) {
      if (err instanceof ProxyError) {
        if (attempt === 0 && (err.status === 404 || /voice/i.test(err.message))) {
          const v = await discoverVoice(base, apiKey);
          if (v && v !== useVoice) { useVoice = v; continue; }
        }
        throw err;
      }
      throw sdkError(err, 502);
    }
    if (json) {
      const b64 = json?.audio_data || json?.audio?.data || json?.data?.audio || null;
      if (!b64) throw new ProxyError('Provider returned an unsupported speech payload.', 502, json);
      return { base64: String(b64), mime: 'audio/mpeg' };
    }
    return { base64: buf.toString('base64'), mime: ct || 'audio/mpeg' };
  }
  throw new ProxyError('Speech synthesis failed.', 502);
}

/* ── speech → text (1.9.0: OpenAI client, proper filename) ─────── */
async function transcribe({ baseUrl, apiKey, model, audio, mime = 'audio/mpeg', timeoutMs = 60000 }) {
  const base = normalizeBaseUrl(baseUrl);
  const client = openaiClient(base, apiKey, timeoutMs);
  if (client) {
    try {
      const buf = Buffer.from(audio, 'base64');
      const file = await toFile(new Uint8Array(buf), `upload.${extForMime(mime)}`, { type: mime || 'audio/mpeg' });
      const json = await client.audio.transcriptions.create({ model, file });
      const text = typeof json?.text === 'string' ? json.text : '';
      if (!text && json == null) throw new ProxyError('Provider returned an unsupported transcription payload.', 502);
      return { text };
    } catch (err) {
      if (err instanceof ProxyError) throw err;
      throw sdkError(err, 400);
    }
  }
  // fallback: manual multipart with a MIME-correct filename (Groq validates it)
  const form = new FormData();
  form.append('file', new Blob([Buffer.from(audio, 'base64')], { type: mime }), `upload.${extForMime(mime)}`);
  form.append('model', model);
  let res;
  try {
    res = await fetch(`${base}/audio/transcriptions`, {
      method: 'POST',
      headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
      body: form,
      signal: composeTimeout(null, timeoutMs),
    });
  } catch (err) { throw networkError(err, base); }
  if (!res.ok) {
    const { msg, body: eb } = await readErrorBody(res);
    throw new ProxyError(msg || `The provider answered ${res.status} on /audio/transcriptions.`, res.status, eb);
  }
  const json = await res.json().catch(() => null);
  const text = json && (json.text || '');
  if (typeof text !== 'string') throw new ProxyError('Provider returned an unsupported transcription payload.', 502, json);
  return { text };
}

module.exports = { listModels, chatCompletion, generateImage, speech, transcribe };
