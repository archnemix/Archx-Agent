// Capture the original browser UI from an isolated, memory-only local server.
// Browser output is evidence, NOT a native implementation or live provider test.
const { chromium } = require(process.env.CAPTURE_MODULE);
const fs = require('node:fs');
const path = require('node:path');
const dir = path.resolve(__dirname, '../Docs/Test_Results/Unreleased/reference');
fs.mkdirSync(dir, { recursive: true });
(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1, reducedMotion: 'reduce' });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    let ready = false;
    for (let attempt = 0; attempt < 15 && !ready; attempt++) {
      try { await page.goto('http://127.0.0.1:4187/#/chat', { waitUntil: 'domcontentloaded', timeout: 5000 }); ready = true; }
      catch { await new Promise(resolve => setTimeout(resolve, 750)); }
    }
    if (!ready) throw Error('Reference server did not become ready');
    await page.locator('#app:not(.hidden)').waitFor({ timeout: 20000 });
    if (await page.locator('#personalization-dialog:not(.hidden)').count()) {
      await page.locator('#personalization-skip').click();
      await page.locator('#personalization-dialog').waitFor({ state: 'hidden' });
    }
    await page.screenshot({ path: path.join(dir, 'reference-chat-1280.png'), animations: 'disabled' });
    await page.locator('.page-nav-btn[data-page="settings"]').click();
    await page.locator('.set-nav-btn[data-sec="models"]').click();
    await page.locator('#sec-models:not(.hidden)').waitFor();
    await page.screenshot({ path: path.join(dir, 'reference-models-1280.png'), animations: 'disabled' });
    fs.writeFileSync(path.join(dir, 'capture-note.txt'), `Original 1.9.0 UI, 1280x800 Chromium viewport, deviceScaleFactor=1. Isolated --no-store server, no API keys, no provider calls requested by capture. ${errors.length ? 'Page errors: ' + errors.join('; ') : 'No page exceptions observed.'}\n`);
    if (errors.length) throw Error('Reference browser errors: ' + errors.join('; '));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
