// Runner-only link-protected preview. Never expose the unguarded app through a tunnel.
const express = require('express');
const crypto = require('crypto');
const { Store } = require('../../lib/store.js');
const { createApp } = require('../../lib/server.js');
const token = process.env.PREVIEW_TOKEN;
if (!token || token.length < 32) throw new Error('A strong preview token is required.');
const store = new Store(process.env.PREVIEW_DATA);
const port = Number(process.env.PREVIEW_PORT || 4173);
const id = 'runner-test-provider';
store.state.providers.providers = [{ id, name: 'Runner models · temporary', adapter: 'openai-compatible', baseUrl: 'http://127.0.0.1:8090/v1', models: { catalog: ['smollm2-135m-q4', 'qwen3:0.6b', 'tts-espeak', 'whisper-tiny', 'ocr-tesseract', 'image-fixture-not-generation'], custom: [], hidden: [], catalogInitialized: true, selectionMode: 'checklist', capabilities: { 'qwen3:0.6b': { chat: true, vision: false } } } }];
store.state.providers.active = { providerId: id, model: 'smollm2-135m-q4' };
store.state.settings.personalizationOnboarded = true;
store.persist('providers');
store.flushWrites();
const app = express();
app.disable('x-powered-by');
const valid = value => {
  const a = Buffer.from(String(value || '')), b = Buffer.from(token);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
};
app.use((req, res, next) => {
  res.set('Referrer-Policy', 'no-referrer').set('Cache-Control', 'no-store');
  if (req.path === '/unlock' && valid(req.query.token)) {
    res.cookie('archx_preview', token, { httpOnly: true, secure: true, sameSite: 'strict', maxAge: 2 * 3600000 });
    return res.redirect('/');
  }
  const cookie = req.headers.cookie?.split('; ').find(c => c.startsWith('archx_preview='))?.slice('archx_preview='.length);
  if (!valid(cookie)) return res.status(401).type('text').send('Temporary test preview. Open the authenticated link from the GitHub preview-link artifact.');
  if (req.method !== 'GET' && req.headers.origin && req.headers.origin !== `https://${req.headers.host}` && !(req.headers.host === `127.0.0.1:${port}` && req.headers.origin === `http://127.0.0.1:${port}`)) return res.status(403).end();
  // Public testing session cannot change host storage or fetch arbitrary URLs.
  if (req.path === '/api/storage' || req.path.startsWith('/api/tools/')) return res.status(403).json({ error: { message: 'Unavailable in the temporary runner preview.' } });
  next();
});
app.use(createApp({ store }));
app.listen(port, '127.0.0.1');
