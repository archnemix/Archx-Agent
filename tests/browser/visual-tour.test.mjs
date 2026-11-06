/*
 * Visual tour.
 *
 * Walks the app the way a person would — chat, studio, memory, debug, every
 * settings tab, both themes, three viewports — and leaves one screenshot per
 * state in test-output/screenshots. Those files are the "did it look right?"
 * half of the run; they are committed by CI so they can be reviewed.
 *
 * A check only fails here if the page throws, fails a request, or an expected
 * panel is missing. Pixel judgement stays with the human reviewing the shots.
 */
import test from 'node:test';
import { Report, ok } from '../helpers/assertions.mjs';
import { startApp, client } from '../helpers/app.mjs';
import { createMockUpstream } from '../mock-upstream/server.mjs';
import {
  launchBrowser,
  openPage,
  goTo,
  VIEWPORTS,
  ACTIVE_VIEWPORTS,
  waitFor,
  humanClick,
  loadPuppeteer,
  ARTIFACT_ROOT,
} from './support.mjs';
import { writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';

const PUPPETEER_ENABLED = process.env.BROWSER_TESTS === '1' || process.env.CI === 'true';

let app;
let mock;
let browser;
const report = new Report('visual-tour');

test.before(async () => {
  if (!PUPPETEER_ENABLED) return;
  mock = createMockUpstream();
  const mockPort = await mock.listen();
  app = await startApp();
  const api = client(app.baseUrl);
  await api.addProvider({ name: 'Mock Provider', baseUrl: `http://127.0.0.1:${mockPort}/v1`, model: 'mock-chat' });
  browser = await launchBrowser(loadPuppeteer());
});

test.after(async () => {
  await browser?.close();
  await app?.stop();
  await mock?.close();
  await mkdir(ARTIFACT_ROOT, { recursive: true });
  await writeFile(path.join(ARTIFACT_ROOT, 'visual-tour.json'), JSON.stringify(report.toJSON(), null, 2));
});

async function tour(name, viewport) {
  const session = await openPage(browser, app.baseUrl, viewport);
  const { page } = session;
  const tag = `${name}`;

  try {
    await report.run(`${tag}-chat`, `chat page renders at ${name}`, async () => {
      await session.shot(`${tag}-01-chat`);
      const hasComposer = await page.$eval('#input', (el) => el.offsetHeight > 20);
      ok(hasComposer, 'the composer is visible and tall enough to type in');
      const version = await page.$eval('#app-version', (el) => el.textContent.trim()).catch(() => '');
      ok(version.length > 0, 'version is shown in the sidebar');
    });

    for (const [pageName, screen] of [
      ['studio', 'studio'],
      ['memory', 'memory'],
      ['debug', 'debug'],
    ]) {
      await report.run(`${tag}-${screen}`, `${screen} page renders at ${name}`, async () => {
        await goTo(page, pageName);
        await session.shot(`${tag}-02-${screen}`);
      });
    }

    const sections = ['general', 'tools', 'generation', 'providers', 'models', 'profiles', 'storage', 'danger'];
    for (const section of sections) {
      await report.run(`${tag}-settings-${section}`, `settings → ${section} at ${name}`, async () => {
        await goTo(page, 'settings', section);
        const visible = await page.evaluate((sec) => {
          const el = document.querySelector(`#sec-${sec}`);
          if (!el) return false;
          const box = el.getBoundingClientRect();
          return !el.classList.contains('hidden') && box.height > 40;
        }, section);
        ok(visible, `#sec-${section} is visible with content`);
        await session.shot(`${tag}-03-settings-${section}`);
      });
    }

    for (const theme of ['light', 'soft', 'dark']) {
      await report.run(`${tag}-theme-${theme}`, `${theme} theme applies at ${name}`, async () => {
        await goTo(page, 'settings', 'general');
        // the real control, not a direct DOM poke: click the theme card
        await page.$eval(`[data-theme-choice="${theme}"]`, (el) => el.scrollIntoView({ block: 'center' }));
        await humanClick(page, `[data-theme-choice="${theme}"]`);
        await waitFor(page, (t) => document.documentElement.dataset.theme === t, {
          label: `theme attribute to become ${theme}`,
          timeout: 5000,
          arg: theme,
        });
        await page.screenshot({ path: (await session.shot(`${tag}-04-theme-${theme}`)), fullPage: false });
        // saveSettings debounces 250 ms before it writes to the server
        const stored = await waitFor(
          page,
          async (want) => {
            const res = await fetch('/api/state');
            const json = await res.json();
            return json.settings.theme === want ? want : false;
          },
          { timeout: 6000, arg: theme, label: `theme ${theme} to be persisted` }
        );
        ok(stored === theme, `theme is persisted server-side (got ${stored})`);
      });
    }

    await report.run(`${tag}-console`, `no console errors during the whole ${name} tour`, async () => {
      const noise = session.consoleErrors.filter((line) => !/favicon|net::ERR_ABORTED/i.test(line));
      ok(noise.length === 0, `console errors: ${noise.slice(0, 3).join(' | ')}`);
    });

    await report.run(`${tag}-network`, `no failed requests during the whole ${name} tour`, async () => {
      ok(session.failedRequests.length === 0, session.failedRequests.slice(0, 3).join(' | '));
    });
  } finally {
    await session.close();
  }
}

for (const [name, viewport] of Object.entries(ACTIVE_VIEWPORTS)) {
  test(`${name} tour`, { skip: !PUPPETEER_ENABLED }, async () => {
    await tour(name, viewport);
  });
}

test('visual tour had no failures', { skip: !PUPPETEER_ENABLED }, async () => {
  const failed = report.failed;
  const summary = failed.map((c) => `${c.id}: ${c.message}`).join('\n');
  ok(failed.length === 0, `${failed.length} visual check(s) failed\n${summary}`);
});
