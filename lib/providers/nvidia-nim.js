'use strict';

/* NVIDIA NIM adapter (1.9.0).
 *
 * Chat + model listing speak the OpenAI wire protocol at
 * https://integrate.api.nvidia.com/v1, but NIM's image / speech / transcription
 * surfaces are NOT OpenAI-shaped:
 *   - image gen:   POST {nim}/v1/genai/{model}        {prompt,cfg_scale,seed…}
 *   - TTS:         POST {nim}/v1/ntts/{model}         {text, voice…}
 *   - ASR:         POST {nim}/v1/asr/{model}          multipart file
 * (self-hosted NIM containers also expose OpenAI-style /v1/images/generations
 *  and /v1/audio/*). Every surface therefore tries the OpenAI-compatible route
 * first and falls through to the native NIM route, so both hosted and
 * self-hosted deployments work; unsupported surfaces fail with a clear error.
 */

const oc = require('./openai-compatible.js');
const { ProxyError } = require('./proxy-error.js');
const { normalizeBaseUrl } = require('../util.js');

const NIM_HOST = 'https://ai.api.nvidia.com';

const headersFor = (apiKey, extra = {}) => ({
  ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
  ...extra,
});

async function tryFetch(url, init, timeoutMs) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(new Error('timeout')), timeoutMs || 60000);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } finally {
    clearTimeout(t);
  }
}

async function readErr(res, label) {
  let body = null;
  try { body = await res.json(); } catch { try { body = (await res.text()).slice(0, 500); } catch {} }
  const msg = body?.error?.message || body?.message || (typeof body === 'string' ? body : null);
  return new ProxyError(msg || `NIM answered ${res.status} on ${label}.`, res.status, body);
}

module.exports = {
  listModels: oc.listModels,
  chatCompletion: oc.chatCompletion,

  async generateImage({ baseUrl, apiKey, model, prompt, image, imageMime, timeoutMs = 90000 }) {
    const base = normalizeBaseUrl(baseUrl);
    // 1) OpenAI-compatible (self-hosted SD/FLUX NIM)
    try {
      return await oc.generateImage({ baseUrl, apiKey, model, prompt, image, imageMime, timeoutMs });
    } catch (err) {
      if (!(err instanceof ProxyError) || (err.status !== 404 && err.status !== 405)) throw err;
    }
    // 2) native hosted route
    const payload = { prompt, cfg_scale: 5, seed: 7, width: 1024, height: 1024, steps: 28 };
    if (image) payload.image = `data:${imageMime || 'image/png'};base64,${image}`;
    const res = await tryFetch(`${NIM_HOST}/v1/genai/${encodeURIComponent(model)}`, {
      method: 'POST',
      headers: headersFor(apiKey, { 'Content-Type': 'application/json', Accept: 'application/json' }),
      body: JSON.stringify(payload),
    }, timeoutMs);
    if (!res.ok) throw await readErr(res, `/v1/genai/${model}`);
    const json = await res.json().catch(() => null);
    const b64 = json?.image || json?.images?.[0]?.image || json?.artifacts?.[0]?.base64 || json?.data?.[0]?.b64_json || null;
    if (!b64) throw new ProxyError('NIM returned no image data.', 502, json);
    return { base64: String(b64).replace(/^data:[^,]+,/, ''), mime: 'image/png' };
  },

  async speech({ baseUrl, apiKey, model, input, voice, timeoutMs = 60000 }) {
    const base = normalizeBaseUrl(baseUrl);
    try {
      return await oc.speech({ baseUrl, apiKey, model, input, voice, timeoutMs });
    } catch (err) {
      if (!(err instanceof ProxyError) || (err.status !== 404 && err.status !== 405)) throw err;
    }
    const res = await tryFetch(`${NIM_HOST}/v1/ntts/${encodeURIComponent(model)}`, {
      method: 'POST',
      headers: headersFor(apiKey, { 'Content-Type': 'application/json', Accept: 'application/json' }),
      body: JSON.stringify({ text: String(input ?? ''), voice_id: voice || 'default' }),
    }, timeoutMs);
    if (!res.ok) throw await readErr(res, `/v1/ntts/${model}`);
    const ct = String(res.headers.get('content-type') || '');
    if (ct.includes('json')) {
      const json = await res.json().catch(() => null);
      const b64 = json?.audio || json?.audio_data || json?.audioBase64 || null;
      if (!b64) throw new ProxyError('NIM returned an unsupported TTS payload.', 502, json);
      return { base64: String(b64), mime: 'audio/mpeg' };
    }
    const buf = Buffer.from(await res.arrayBuffer());
    return { base64: buf.toString('base64'), mime: ct || 'audio/mpeg' };
  },

  async transcribe({ baseUrl, apiKey, model, audio, mime = 'audio/mpeg', timeoutMs = 60000 }) {
    const base = normalizeBaseUrl(baseUrl);
    try {
      return await oc.transcribe({ baseUrl, apiKey, model, audio, mime, timeoutMs });
    } catch (err) {
      if (!(err instanceof ProxyError) || (err.status !== 404 && err.status !== 405)) throw err;
    }
    const form = new FormData();
    const ext = { 'audio/wav': 'wav', 'audio/x-wav': 'wav', 'audio/flac': 'flac', 'audio/opus': 'opus' }[String(mime).toLowerCase()] || 'wav';
    form.append('file', new Blob([Buffer.from(audio, 'base64')], { type: mime }), `upload.${ext}`);
    const res = await tryFetch(`${NIM_HOST}/v1/asr/${encodeURIComponent(model)}`, {
      method: 'POST',
      headers: headersFor(apiKey),
      body: form,
    }, timeoutMs);
    if (!res.ok) throw await readErr(res, `/v1/asr/${model}`);
    const text = await res.text();
    try { const j = JSON.parse(text); return { text: String(j.text ?? j.transcript ?? '') }; }
    catch { return { text }; }
  },
};
