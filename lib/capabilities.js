'use strict';

/*
 * Model capability inference (1.8.0).
 *
 * Every model id that enters the app is classified into capability buckets so
 * each surface (Chat, Image studio, Audio lab, Vision/OCR) only offers models
 * that can actually do the job. Classification is heuristic over the remote
 * model id (providers do not expose reliable capability metadata on the
 * OpenAI-compatible wire), and every guess can be overridden per model from
 * Settings → Models → capabilities.
 *
 * Buckets:
 *   chat     — text in / text out (the simple-chat picker)
 *   vision   — accepts image input (also powers the OCR surface)
 *   imageGen — produces images
 *   video    — produces video
 *   tts      — text → speech
 *   stt      — speech → text
 */

const RULES = [
  // text-to-speech
  { cap: 'tts', re: /(^|[:/_-])(tts|speech|voxtral-small-tts|voxtral-tts)/i },
  { cap: 'tts', re: /-tts-\d/i },
  // speech-to-text
  { cap: 'stt', re: /(whisper|transcrib|scribe|voxtral-mini.*transcribe|voxtral.*transcribe|stt|asr)/i },
  // image generation
  { cap: 'imageGen', re: /(image|flux|sdxl|stable-?diffusion|dall-?e|ideogram|midjourney|nano-banana|gpt-image|imagine)/i },
  // video generation
  { cap: 'video', re: /(veo|sora|kling|ltx|wan-|video|animate|motion)/i },
];

/* Vision (image-understanding) models: explicit families known to accept
   image input. Pure TTS/STT/image-only models are NOT chat models. */
const VISION_RE = /(gpt-4o|gpt-4\.1|gpt-4-turbo|gpt-5|o1|o3|o4|gemini|claude|vision|-vl|llava|nano-banana|pixtral|mistral-large|mistral-medium|mistral-small|voxtral-small(?!-tts)|qwen|internvl|phi-3|phi-4|pro-latest)/i;
const IMAGE_GEN_RE = /(image|flux|sdxl|stable-?diffusion|dall-?e|ideogram|midjourney|nano-banana|gpt-image|imagine)/i;
const TTS_RE = /(^|[:/_-])(tts|speech)/i;
const STT_RE = /(whisper|transcrib|scribe|stt|asr)/i;

function inferCapabilities(modelId) {
  const lower = String(modelId || '').toLowerCase();
  const caps = { chat: false, vision: false, imageGen: false, video: false, tts: false, stt: false };

  /* 1.9.0 rewrite (validation fix): classify dedicated-purpose models FIRST
     so a TTS/transcribe/embedding id can never leak into Chat or Vision/OCR. */
  const isTts   = /(^|[:/_-])tts([:_/-]|$)/.test(lower) || /-tts-|tts-\d|tts-preview|speech/.test(lower) || /voxtral-[a-z-]*tts/.test(lower);
  const isStt   = /(whisper|transcrib|scribe|stt|asr|parakeet)/.test(lower);
  const isImage = /(image|flux|sdxl|stable-?diffusion|dall-?e|ideogram|midjourney|nano-banana|gpt-image|imagine)/.test(lower);
  const isVideo = /(^|[:/_-])(veo|sora|kling|ltx|wan|video)([:/_-]|$)/.test(lower) || /animate|motion/.test(lower);
  const isOcr   = /(^|[:/_-])ocr/.test(lower);
  const isUtil  = /(embed|embedding|moderation|guard|-fim|code-fim|computer-use|deep-research)/.test(lower);

  caps.tts = isTts; caps.stt = isStt; caps.imageGen = isImage; caps.video = isVideo;

  if (isUtil) return caps;                                   // embeddings/moderation/fim/research: no studio surface
  if (isTts && !isStt) return caps;                          // pure speech synthesis
  if (isStt && !isTts && !/voxtral-(mini-|small-)?latest/.test(lower)) return caps;  // pure transcription

  caps.chat = !isVideo;
  const VISION_RE = /(gpt-4o|gpt-4\.1|gpt-4-turbo|gpt-5|\bo1\b|\bo3\b|\bo4\b|gemini|claude|vision|-vl|llava|pixtral|mistral-large|mistral-medium|mistral-small|ministral|qwen|internvl|phi-3|phi-4|grok|ocr)/i;
  caps.vision = VISION_RE.test(lower) || (isImage && /gemini|gpt-image|nano-banana/.test(lower));
  if (isOcr) { caps.vision = true; caps.chat = false; }      // OCR-only engines read, they don't chat
  if (isImage && !/gemini|nano-banana/.test(lower)) { caps.chat = false; caps.vision = false; }  // dedicated generators don't chat
  if (/gemini/.test(lower) && caps.chat) caps.stt = true;      // gemini chat models transcribe audio natively
  if (/voxtral-(mini-|small-)?latest/.test(lower)) caps.stt = true;
  if (isVideo) caps.vision = false;
  return caps;
}/* Merge stored per-model overrides ({chat:bool,...}) on top of the guess. */
function capabilitiesFor(modelId, override) {
  const caps = inferCapabilities(modelId);
  if (override && typeof override === 'object') {
    for (const k of Object.keys(caps)) {
      if (typeof override[k] === 'boolean') caps[k] = override[k];
    }
  }
  return caps;
}

/* ── default test documents per model type (issue 7) ─────────────────────
 * Each capability gets a small default probe so "test" actually exercises the
 * surface the model advertises. Users can replace the request body per model
 * (saved on the provider) and restore these defaults at any time. */
const DEFAULT_TEST_BODIES = {
  chat: {
    label: 'Text probe',
    body: { message: 'Reply with exactly: ARCHX_OK' },
  },
  vision: {
    label: 'Image + text probe (1×1 red PNG)',
    body: {
      message: 'Describe this image in one word.',
      image: 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
      imageMime: 'image/png',
    },
  },
  imageGen: {
    label: 'Image generation probe',
    body: { prompt: 'A minimal white letter A on a black square.' },
  },
  tts: {
    label: 'Speech synthesis probe',
    body: { input: 'Archx agent audio check.' },
  },
  stt: {
    label: 'Transcription probe (short WAV)',
    body: { audio: null, note: 'STT models need a real audio sample; the batch tester verifies reachability + auth instead.' },
  },
  video: {
    label: 'Video probe (reachability only)',
    body: { prompt: 'A red square.' },
  },
};

function defaultTestBodyFor(modelId, capsOverride) {
  const caps = capabilitiesFor(modelId, capsOverride);
  if (caps.stt) return { kind: 'stt', ...DEFAULT_TEST_BODIES.stt };
  if (caps.tts && !caps.chat) return { kind: 'tts', ...DEFAULT_TEST_BODIES.tts };
  if (caps.imageGen && !caps.chat) return { kind: 'imageGen', ...DEFAULT_TEST_BODIES.imageGen };
  if (caps.vision) return { kind: 'vision', ...DEFAULT_TEST_BODIES.vision };
  return { kind: 'chat', ...DEFAULT_TEST_BODIES.chat };
}

module.exports = { inferCapabilities, capabilitiesFor, defaultTestBodyFor, DEFAULT_TEST_BODIES };
