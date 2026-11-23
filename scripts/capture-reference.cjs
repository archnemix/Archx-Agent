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
    // Visual-only fixture: let the real CSS lay out the original modal DOM.
    // No model fetch/test/import is invoked; statuses are synthetic, as in the
    // native import screenshot, and must never be called provider evidence.
    await page.evaluate(() => {
      const dialog = document.querySelector('#model-import-dialog');
      dialog.classList.remove('hidden');
      document.querySelector('#model-import-title').textContent = 'Add models from OpenRouter';
      document.querySelector('#model-import-subtitle').textContent = 'Choose exactly which models should be added to your local list. Unchecked models are not added.';
      document.querySelector('#model-import-count').textContent = '3 new models found · 1 verified working · 1 failed';
      const list = document.querySelector('#model-import-list');
      list.replaceChildren();
      for (const [id, status, checked, outcome] of [
        ['vendor/alpha:free', '', false, ''],
        ['vendor/beta', '✓ works · 42 ms', true, 'passed'],
        ['vendor/gamma', '✗ HTTP 429 · account quota exceeded', true, 'failed'],
      ]) {
        const row = document.createElement('label'); row.className = `model-import-row ${outcome}`;
        const main = document.createElement('span'); main.className = 'model-import-main';
        const dot = document.createElement('span'); dot.className = `model-row-dot ${outcome === 'passed' ? 'on' : ''}`;
        const name = document.createElement('span'); name.className = 'model-row-name'; name.textContent = id;
        main.append(dot, name);
        if (id.endsWith(':free')) { const tag = document.createElement('span'); tag.className = 'mini-tag free'; tag.textContent = 'free'; main.append(tag); }
        if (status) { const tag = document.createElement('span'); tag.className = `mini-tag import-${outcome === 'passed' ? 'ok' : 'bad'}`; tag.textContent = status; main.append(tag); }
        const box = document.createElement('input'); box.type = 'checkbox'; box.checked = checked; box.dataset.importModel = id;
        row.append(main, box); list.append(row);
      }
    });
    await page.screenshot({ path: path.join(dir, 'reference-import-fixture-1280.png'), animations: 'disabled' });
    fs.writeFileSync(path.join(dir, 'capture-note.txt'), `Original 1.9.0 UI: chat and models are unmodified screens at 1280x800 Chromium viewport, deviceScaleFactor=1. The import screen uses original HTML/CSS with three synthetic DOM rows; NO model fetch, probe or import was performed. Isolated --no-store server, no API keys. ${errors.length ? 'Page errors: ' + errors.join('; ') : 'No page exceptions observed.'}\n`);
    if (errors.length) throw Error('Reference browser errors: ' + errors.join('; '));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
