// Actual model + actual UI. Runs on the inference runner, not a simulated provider.
import { pathToFileURL } from 'node:url';
const moduleName = process.env.PLAYWRIGHT_MODULE || 'playwright';
const { chromium } = await import(moduleName.startsWith('/') ? pathToFileURL(moduleName) : moduleName);
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
const output = `${process.env.RUNNER_TEMP || '/tmp'}/real-model-evidence`;
mkdirSync(output, { recursive: true });
const launch = { headless: true };
if (process.env.SPARTICUZ_MODULE) {
  const { default: binary } = await import(pathToFileURL(process.env.SPARTICUZ_MODULE));
  launch.executablePath = await binary.executablePath(); launch.args = binary.args;
}
const browser = await chromium.launch(launch);
const base = process.env.PREVIEW_URL || 'http://127.0.0.1:4173';
let page;
const errors = [];
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  await context.addCookies([{ name: 'archx_preview', value: process.env.PREVIEW_TOKEN, url: base, httpOnly: true, sameSite: 'Strict' }]);
  page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(base);
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
  const savedCompletion = page.waitForResponse(response => {
    if (!response.url().endsWith('/api/state/chat') || response.request().method() !== 'POST') return false;
    const chat = response.request().postDataJSON()?.chat;
    return chat?.messages.length === 4 && !chat.messages.at(-1).pending;
  });
  const second = await send('What did I ask you in my previous message? Answer briefly.');
  assert.ok((await savedCompletion).ok(), 'Final conversation save must be acknowledged');
  const history = await page.evaluate(() => {
    const s = window.__archxState; return s.chats.find(c => c.id === s.activeId).messages;
  });
  assert.equal(history.length, 4);
  // Verify the response body in Node, not a Promise-valued browser predicate.
  const stored = await (await context.request.get(base + '/api/state')).json();
  assert.equal(stored.chats.find(c => c.messages.length === 4)?.messages.at(-1).pending, false);
  await page.reload();
  await page.waitForFunction(() => window.__archxState?.chats.some(c => c.messages.length === 4));
  assert.deepEqual(errors, []);
  await page.screenshot({ path: `${output}/smollm-q4-chat.png` });
  writeFileSync(`${output}/conversation.json`, JSON.stringify({ model: 'SmolLM2 135M Q4_K_M via Ollama', first, second, history, errors }, null, 2));
  console.log('PASS: actual SmolLM2 Q4 streamed UI conversation, follow-up, persistence and reload; zero browser errors.');
  // Remove verification conversation so the user receives a clean workspace.
  const chatId = await page.evaluate(() => window.__archxState.activeId);
  const deleted = await context.request.delete(base + '/api/library/item', { data: { kind: 'chats', id: chatId } });
  assert.ok(deleted.ok(), 'Verification conversation cleanup failed');
} catch (error) {
  if (page) {
    const state = await page.evaluate(() => ({ url: location.href, chats: window.__archxState?.chats.map(c => ({ id: c.id, messages: c.messages.length })), text: document.body.innerText.slice(0, 2500) })).catch(() => null);
    console.error('Browser failure state:', JSON.stringify({ state, errors }));
    await page.screenshot({ path: `${output}/failure.png` }).catch(() => {});
  }
  throw error;
} finally { await browser.close(); }
