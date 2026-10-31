// Actual model + actual UI. Runs on the inference runner, not a simulated provider.
import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
const output = `${process.env.RUNNER_TEMP || '/tmp'}/real-model-evidence`;
mkdirSync(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const errors = [];
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  await context.addCookies([{ name: 'archx_preview', value: process.env.PREVIEW_TOKEN, url: 'http://127.0.0.1:4173', httpOnly: true, sameSite: 'Strict' }]);
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:4173');
  await page.waitForFunction(() => window.__archxState?.active?.model === 'smollm2-135m-q4');
  if (await page.locator('#personalization-skip').isVisible()) await page.click('#personalization-skip');
  const send = async text => {
    await page.fill('#input', text);
    await page.click('#btn-send');
    await page.waitForFunction(() => {
      const s = window.__archxState;
      const last = s.chats.find(c => c.id === s.activeId)?.messages.at(-1);
      return last?.role === 'assistant' && !last.pending;
    }, null, { timeout: 180000 });
    const message = await page.evaluate(() => {
      const s = window.__archxState; return s.chats.find(c => c.id === s.activeId).messages.at(-1);
    });
    assert.equal(!!message.error, false, message.errorMessage);
    assert.ok(message.content.trim(), 'Actual model must return text');
    return message.content;
  };
  const first = await send('Hello! Please introduce yourself in one short sentence.');
  const second = await send('What did I ask you in my previous message? Answer briefly.');
  const history = await page.evaluate(() => {
    const s = window.__archxState; return s.chats.find(c => c.id === s.activeId).messages;
  });
  assert.equal(history.length, 4);
  // Wait for acknowledged server persistence before checking a real reload.
  await page.waitForFunction(async () => {
    const s = window.__archxState;
    const saved = await (await fetch('/api/state')).json();
    return saved.chats.find(c => c.id === s.activeId)?.messages.length === 4 && !saved.chats.find(c => c.id === s.activeId).messages.at(-1).pending;
  });
  await page.reload();
  await page.waitForFunction(() => window.__archxState?.chats.some(c => c.messages.length === 4));
  assert.deepEqual(errors, []);
  await page.screenshot({ path: `${output}/smollm-q4-chat.png` });
  writeFileSync(`${output}/conversation.json`, JSON.stringify({ model: 'SmolLM2 135M Q4_K_M via Ollama', first, second, history, errors }, null, 2));
  console.log('PASS: actual SmolLM2 Q4 streamed UI conversation, follow-up, persistence and reload; zero browser errors.');
  // Remove verification conversation so the user receives a clean workspace.
  const chatId = await page.evaluate(() => window.__archxState.activeId);
  const deleted = await context.request.delete('http://127.0.0.1:4173/api/library/item', { data: { kind: 'chats', id: chatId } });
  assert.ok(deleted.ok(), 'Verification conversation cleanup failed');
} finally { await browser.close(); }
