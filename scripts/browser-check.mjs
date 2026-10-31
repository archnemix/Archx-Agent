// Optional real-browser check. Uses a temporary database and a local fake provider,
// never saved credentials or the user's data area. See the technical guide.
import assert from 'node:assert/strict';
import http from 'node:http';
import { mkdtempSync, rmSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';

const temp = mkdtempSync(join(tmpdir(), 'archx-browser-'));
process.env.XDG_CONFIG_HOME = join(temp, 'config');
const { Store } = await import('../lib/store.js');
const { createApp } = await import('../lib/server.js');
const moduleName = process.env.PLAYWRIGHT_MODULE || 'playwright';
const { chromium } = await import(moduleName.startsWith('/') ? pathToFileURL(moduleName) : moduleName);
const launch = { headless: true, args: ['--no-sandbox'] };
if (process.env.SPARTICUZ_MODULE) {
  const imported = await import(pathToFileURL(process.env.SPARTICUZ_MODULE));
  const binary = imported.default;
  launch.executablePath = await binary.executablePath();
  launch.args = binary.args;
}
const listen = server => new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(server.address().port)));
const close = server => new Promise(resolve => { server.closeAllConnections(); server.close(resolve); });
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const upstream = http.createServer(async (req, res) => {
  if (req.url.endsWith('/models')) return res.end(JSON.stringify({ data: [{ id: 'fixture-model' }] }));
  let raw = '';
  for await (const chunk of req) raw += chunk;
  const body = JSON.parse(raw);
  if (!body.stream) return res.end(JSON.stringify({ choices: [{ message: { content: 'Fixture connection OK' } }] }));
  const prompt = body.messages.filter(x => x.role === 'user').at(-1)?.content || '';
  res.writeHead(200, { 'Content-Type': 'text/event-stream' });
  const delta = value => { if (!res.destroyed) res.write(`data: ${JSON.stringify({ choices: [{ delta: value }] })}\n\n`); };
  delta({ reasoning_content: `Reasoning for ${prompt}` });
  delta({ content: `Partial ${prompt}. ` });
  await sleep(prompt.includes('slow') ? 1800 : 100);
  if (res.destroyed) return;
  if (prompt.includes('truncated')) return res.end();
  delta({ content: 'Complete answer.\n\n```js\nconst working = true;\n```' });
  res.end('data: [DONE]\n\n');
});
let browser, server, store;
const errors = [];
const output = resolve(process.env.BROWSER_OUTPUT || 'test-results/browser');
mkdirSync(output, { recursive: true });
try {
  const port = await listen(upstream);
  store = new Store(join(temp, 'data'));
  server = http.createServer(createApp({ store }));
  const appPort = await listen(server);
  browser = await chromium.launch(launch);
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${appPort}`);
  await page.waitForFunction(() => window.__archxState?.storage);
  if (await page.locator('#personalization-skip').isVisible()) await page.click('#personalization-skip');
  await page.getByRole('button', { name: 'Add a provider', exact: true }).click();
  await page.fill('#prov-name', 'Local test fixture');
  await page.fill('#prov-url', `http://127.0.0.1:${port}/v1`);
  await page.click('#prov-test');
  await page.waitForFunction(() => document.querySelector('#prov-status').textContent.startsWith('Reachable'));
  await page.click('#prov-save');
  await page.locator('#model-import-dialog').waitFor({ state: 'visible' });
  await page.click('#model-import-select-all');
  await page.click('#model-import-add');
  await page.locator('#model-import-dialog').waitFor({ state: 'hidden' });
  await page.click('[data-page="chat"]');
  await page.click('#model-btn');
  await page.click('.model-opt[data-model="fixture-model"]');
  const send = async text => { await page.fill('#input', text); await page.click('#btn-send'); };
  const activeId = () => page.evaluate(() => window.__archxState.activeId);
  const done = id => page.waitForFunction(id => {
    const chat = window.__archxState.chats.find(x => x.id === id);
    return chat?.messages.some(x => x.role === 'assistant' && !x.pending);
  }, id);
  await send('slow conversation A');
  const first = await activeId();
  await page.waitForFunction(() => document.querySelector('.thinking-body')?.textContent.includes('conversation A'));
  await page.click('#new-chat');
  await send('conversation B');
  const second = await activeId();
  await done(second);
  await done(first);
  const chats = await page.evaluate(() => window.__archxState.chats);
  assert.match(chats.find(x => x.id === first).messages.at(-1).content, /Partial slow conversation A.*Complete/s);
  assert.match(chats.find(x => x.id === second).messages.at(-1).reasoning, /conversation B/);
  assert.doesNotMatch(await page.locator('#messages').innerText(), /conversation A/);
  await page.screenshot({ path: join(output, 'chat.png') });
  await page.click('#new-chat');
  await send('truncated response');
  const incomplete = await activeId();
  await done(incomplete);
  await page.locator('.msg-failure').waitFor({ state: 'visible' });
  assert.match(await page.locator('#messages').innerText(), /Partial truncated response/);
  await page.screenshot({ path: join(output, 'interrupted.png') });
  await page.click('#new-chat');
  await send('slow stopped response');
  const stopped = await activeId();
  await page.waitForFunction(() => document.querySelector('.thinking-body')?.textContent.includes('stopped response'));
  await page.click('#btn-stop');
  await done(stopped);
  assert.equal(await page.evaluate(() => window.__archxState.chats.find(x => x.id === window.__archxState.activeId).messages.at(-1).meta.stopped), true);
  // Poll the real persistence endpoint rather than assuming a debounce finished.
  await page.waitForFunction(async ids => {
    const saved = await (await fetch('/api/state')).json();
    return ids.every(id => saved.chats.find(x => x.id === id)?.messages.at(-1)?.pending === false);
  }, [first, second, incomplete, stopped]);
  await page.reload();
  await page.waitForFunction(() => window.__archxState?.storage);
  const restored = await page.evaluate(() => window.__archxState.chats);
  assert.match(restored.find(x => x.id === incomplete).messages.at(-1).errorMessage, /completion|ended|stream/i);
  assert.match(restored.find(x => x.id === first).messages.at(-1).reasoning, /conversation A/);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: join(output, 'mobile.png') });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false, 'mobile page must not overflow horizontally');
  assert.deepEqual(errors, []);
  console.log('PASS: real provider setup/import, two concurrent chats, reasoning, code, interrupted answer, Stop, persisted reload, mobile width; 0 browser errors.');
  console.log(`Screenshots: ${output}`);
} finally {
  if (browser) await browser.close();
  if (server) await close(server);
  await close(upstream);
  store?.close();
  rmSync(temp, { recursive: true, force: true });
}
