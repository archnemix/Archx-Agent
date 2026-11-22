'use strict';

/*
 * Anthropic-native provider adapter (Claude models).
 * Wire protocol: https://docs.anthropic.com — POST /messages with
 * `x-api-key` + `anthropic-version` headers; SSE events
 * (message_start / content_block_delta / message_delta / message_stop).
 * System messages are lifted into the top-level `system` field, because the
 * Messages API does not accept role:"system" inside `messages`.
 * Thinking output (extended thinking / interleaved thinking) is surfaced as
 * reasoning through `thinking_delta` deltas and `thinking` content blocks.
 */

const { ProxyError } = require('./proxy-error.js');
/* 1.9.0: official Anthropic SDK for non-streaming calls; the streaming path
   stays a raw SSE passthrough (same wire format as the SDK). */
let AnthropicCtor = null;
try { ({ Anthropic: AnthropicCtor } = require('@anthropic-ai/sdk')); } catch { /* optional */ }

const ANTHROPIC_VERSION = '2023-06-01';

function headersFor(apiKey) {
  const h = {
    'Content-Type': 'application/json',
    Accept: 'application/json',
    'anthropic-version': ANTHROPIC_VERSION,
  };
  if (apiKey) h['x-api-key'] = apiKey;
  return h;
}

/** Anthropic base URLs look like https://api.anthropic.com/v1 (or /v1-less hosts). */
function baseOf(baseUrl) {
  let base = String(baseUrl || '').trim().replace(/\/+$/, '');
  if (!base) throw new ProxyError('Base URL is required.', 400);
  if (!/^https?:\/\//i.test(base)) base = 'https://' + base;
  let u;
  try {
    u = new URL(base);
  } catch {
    throw new ProxyError(`"${baseUrl}" is not a valid URL.`, 400);
  }
  if (!u.pathname || u.pathname === '/') u.pathname = '/v1';
  return u.toString().replace(/\/+$/, '');
}

async function readErrorBody(res) {
  let body = null;
  try {
    const text = await res.text();
    try { body = JSON.parse(text); } catch { body = text ? text.slice(0, 2000) : null; }
  } catch { /* ignore */ }
  const msg =
    (body && body.error && (body.error.message || body.error.type)) ||
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
    cause === 'CERT_HAS_EXPIRED' || cause === 'UNABLE_TO_VERIFY_LEAF_SIGNATURE' || cause === 'SELF_SIGNED_CERT_IN_CHAIN' ? 'TLS certificate problem (self-signed local endpoints may need NODE_EXTRA_CA_CERTS).' :
    `Network error${cause ? ` (${cause})` : ''}.`;
  return new ProxyError(`${hint} [${base}]`, 502, String((err && err.message) || err));
}

/** Split OpenAI-style messages into Anthropic `system` + `messages`. */
function convertMessages(messages) {
  const system = [];
  const out = [];
  for (const m of Array.isArray(messages) ? messages : []) {
    if (!m || typeof m.content !== 'string') continue;
    if (m.role === 'system') { system.push(m.content); continue; }
    const role = m.role === 'assistant' ? 'assistant' : 'user';
    // Anthropic rejects consecutive same-role turns in some validators; merge them.
    const last = out[out.length - 1];
    if (last && last.role === role) last.content += '\n\n' + m.content;
    else out.push({ role, content: m.content });
  }
  return { system: system.join('\n\n'), messages: out };
}

async function listModels({ baseUrl, apiKey, timeoutMs = 20000, signal } = {}) {
  const base = baseOf(baseUrl);
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
  const list = Array.isArray(json) ? json : Array.isArray(json && json.data) ? json.data : null;
  if (!list) throw new ProxyError('Provider returned an unexpected /models payload.', 502, json);
  return list
    .map((m) => (typeof m === 'string' ? { id: m } : m))
    .filter((m) => m && typeof m.id === 'string' && m.id.length)
    .map((m) => ({ id: m.id, owned_by: m.owned_by || 'anthropic', created: m.created_at || undefined }))
    .sort((a, b) => a.id.localeCompare(b.id));
}

function buildBody(opts, system, messages) {
  const body = {
    model: opts.model,
    messages,
    max_tokens: Number(opts.maxTokens) > 0 ? Number(opts.maxTokens) : 4096,
    stream: !!opts.stream,
  };
  if (system) body.system = system;
  if (typeof opts.temperature === 'number' && !Number.isNaN(opts.temperature)) body.temperature = Math.min(1, Math.max(0, opts.temperature));
  return body;
}

async function chatCompletion(opts, cb = {}) {
  const base = baseOf(opts.baseUrl);
  const { system, messages } = convertMessages(opts.messages);
  if (!messages.length) throw new ProxyError('Anthropic requires at least one user message.', 400);
  const body = buildBody(opts, system, messages);

  if (!opts.stream && AnthropicCtor) {
    try {
      const client = new AnthropicCtor({ apiKey: opts.apiKey || undefined, baseURL: base, maxRetries: 0, timeout: opts.timeoutMs || 60000 });
      const msg = await client.messages.create({ ...body, stream: undefined });
      let text = '';
      let reasoning = '';
      for (const block of msg.content || []) {
        if (!block) continue;
        if (block.type === 'text' && typeof block.text === 'string') text += block.text;
        else if (block.type === 'thinking' && typeof block.thinking === 'string') reasoning += block.thinking;
      }
      return { text, reasoning: reasoning || undefined, finish: msg.stop_reason || 'stop', raw: msg };
    } catch (err) {
      if (err instanceof ProxyError) throw err;
      throw new ProxyError(err?.error?.message || err?.message || 'Anthropic request failed.', Number(err?.status) || 502, err?.error || null);
    }
  }

  let res;
  try {
    res = await fetch(`${base}/messages`, {
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
    throw new ProxyError(msg || `The provider answered ${res.status} ${res.statusText || ''} on /messages.`, res.status, eb);
  }

  if (!opts.stream) {
    const json = await res.json().catch(() => null);
    if (!json || !Array.isArray(json.content)) throw new ProxyError('Provider returned an unexpected /messages payload.', 502, json);
    let text = '';
    let reasoning = '';
    for (const block of json.content) {
      if (!block) continue;
      if (block.type === 'text' && typeof block.text === 'string') text += block.text;
      else if (block.type === 'thinking' && typeof block.thinking === 'string') reasoning += block.thinking;
    }
    if (cb.onMeta) cb.onMeta({ usage: json.usage ? { prompt_tokens: json.usage.input_tokens, completion_tokens: json.usage.output_tokens, total_tokens: (json.usage.input_tokens || 0) + (json.usage.output_tokens || 0) } : null, model: json.model || opts.model });
    if (reasoning && cb.onReasoning) cb.onReasoning(reasoning);
    return { text, reasoning, model: json.model || opts.model, usage: json.usage ? { prompt_tokens: json.usage.input_tokens, completion_tokens: json.usage.output_tokens } : null };
  }

  if (!res.body) throw new ProxyError('Provider returned an empty streaming body.', 502);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let full = '';
  let fullReasoning = '';
  let usage = null;
  let respModel = null;

  const handleEvent = (type, ev) => {
    if (!ev || typeof ev !== 'object') return;
    if (type === 'message_start') {
      respModel = ev.message && ev.message.model ? ev.message.model : respModel;
      if (ev.message && ev.message.usage) {
        usage = {
          prompt_tokens: ev.message.usage.input_tokens,
          completion_tokens: ev.message.usage.output_tokens,
        };
      }
      return;
    }
    if (type === 'content_block_delta') {
      const d = ev.delta || {};
      if (d.type === 'text_delta' && typeof d.text === 'string' && d.text) {
        full += d.text;
        if (cb.onDelta) cb.onDelta(d.text);
      } else if (d.type === 'thinking_delta' && typeof d.thinking === 'string' && d.thinking) {
        fullReasoning += d.thinking;
        if (cb.onReasoning) cb.onReasoning(d.thinking);
      }
      return;
    }
    if (type === 'message_delta') {
      if (ev.usage) {
        usage = {
          ...(usage || {}),
          completion_tokens: ev.usage.output_tokens != null ? ev.usage.output_tokens : usage && usage.completion_tokens,
        };
      }
      return;
    }
    if (type === 'error') {
      const msg = (ev.error && ev.error.message) || 'Provider stream error.';
      throw new ProxyError(msg, 502, ev.error);
    }
  };

  const handleLine = (line) => {
    const trimmed = line.trim();
    if (!trimmed.startsWith('data:')) return;
    const payload = trimmed.slice(5).trim();
    if (!payload || payload === '[DONE]') return;
    let j;
    try { j = JSON.parse(payload); } catch { return; }
    handleEvent(j.type, j);
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
  if (usage && (usage.prompt_tokens != null || usage.completion_tokens != null)) {
    usage.total_tokens = (usage.prompt_tokens || 0) + (usage.completion_tokens || 0);
  }
  if (cb.onMeta) cb.onMeta({ usage, model: respModel || opts.model });
  return { text: full, reasoning: fullReasoning, model: respModel || opts.model, usage };
}

/* 1.8.0: media surfaces are not implemented for the Anthropic-native wire
   protocol yet — surface a clean error instead of a crash. */
const { ProxyError: PE } = require('./proxy-error.js');
const notSupported = (what) => () => { throw new PE(`This provider adapter does not support ${what} yet.`, 501); };
const generateImage = notSupported('image generation');
const speech = notSupported('text-to-speech');
const transcribe = notSupported('transcription');

module.exports = { listModels, chatCompletion, generateImage, speech, transcribe };
