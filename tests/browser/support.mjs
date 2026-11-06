/*
 * Shared browser plumbing.
 *
 * Every visual test runs the same three viewports, because "looks fine on my
 * 1440p monitor" is how mobile layouts ship broken.  Console errors and failed
 * requests are collected per page: a page that renders correctly while
 * throwing is still a broken page.
 */
import { mkdir } from 'node:fs/promises';
import path from 'node:path';

export const ARTIFACT_ROOT = process.env.ARTIFACT_DIR || path.resolve(import.meta.dirname, '..', '..', 'test-output');

export const VIEWPORTS = {
  desktop: { width: 1440, height: 900 },
  laptop: { width: 1280, height: 800 },
  mobile: { width: 390, height: 844 },
};

/**
 * CI fans the visual tour out across runners, one viewport per job, and tells
 * each job which slice it owns.  Locally everything runs in one process.
 */
export const ACTIVE_VIEWPORTS = process.env.TEST_VIEWPORT
  ? Object.fromEntries(Object.entries(VIEWPORTS).filter(([name]) => name === process.env.TEST_VIEWPORT))
  : VIEWPORTS;

export async function launchBrowser(puppeteer) {
  const chromium = (await import('@sparticuz/chromium')).default;
  const args = [...chromium.args, '--no-sandbox', '--disable-dev-shm-usage', '--font-render-hinting=none'];
  const executablePath = process.env.CHROME_PATH || (await chromium.executablePath());
  return puppeteer.launch({ executablePath, args, headless: 'shell', protocolTimeout: 120000 });
}

/** One page, with console/network problems recorded rather than printed. */
export async function openPage(browser, baseUrl, viewport = VIEWPORTS.desktop) {
  const page = await browser.newPage();
  await page.setViewport({ ...viewport, deviceScaleFactor: 1 });

  const consoleErrors = [];
  const failedRequests = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (error) => consoleErrors.push(`pageerror: ${error.message}`));
  page.on('requestfailed', (request) => {
    // aborted fetches are normal (stop button, navigation); only real failures matter
    const reason = request.failure()?.errorText || '';
    if (!/ERR_ABORTED/.test(reason)) failedRequests.push(`${request.method()} ${request.url()} — ${reason}`);
  });

  await page.goto(baseUrl, { waitUntil: 'networkidle2', timeout: 30000 });
  await page.waitForSelector('#input', { timeout: 15000 });

  return {
    page,
    consoleErrors,
    failedRequests,
    async shot(name) {
      const dir = path.join(ARTIFACT_ROOT, 'screenshots');
      await mkdir(dir, { recursive: true });
      const file = path.join(dir, `${name}.png`);
      await page.screenshot({ path: file, fullPage: false });
      return file;
    },
    async fullShot(name) {
      const dir = path.join(ARTIFACT_ROOT, 'screenshots');
      await mkdir(dir, { recursive: true });
      const file = path.join(dir, `${name}-full.png`);
      await page.screenshot({ path: file, fullPage: true });
      return file;
    },
    async close() {
      await page.close();
    },
  };
}

/**
 * Is the element actually reachable by a mouse at its own centre?
 * Puppeteer's .click() scrolls and clicks regardless of overlays, so it happily
 * "clicks" a button hidden behind a toast. elementFromPoint does not lie.
 */
export async function isHittable(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return { found: false, reason: 'missing' };
    const box = el.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) return { found: true, hittable: false, reason: 'zero-size' };
    const x = box.left + box.width / 2;
    const y = box.top + box.height / 2;
    if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) {
      return { found: true, hittable: false, reason: 'offscreen', box };
    }
    const hit = document.elementFromPoint(x, y);
    const contains = hit === el || el.contains(hit) || (hit && hit.contains(el));
    return {
      found: true,
      hittable: !!contains,
      reason: contains ? null : `covered by ${hit ? hit.tagName.toLowerCase() + '.' + String(hit.className).split(' ')[0] : 'nothing'}`,
      box,
    };
  }, selector);
}

/** Real mouse click: scroll into view, confirm nothing covers it, then click. */
export async function humanClick(page, selector) {
  await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (el) el.scrollIntoView({ block: 'center', inline: 'center' });
  }, selector);
  const check = await isHittable(page, selector);
  if (!check.found) throw new Error(`cannot click ${selector} — element missing`);
  if (!check.hittable) throw new Error(`cannot click ${selector} — ${check.reason}`);
  const box = check.box;
  await page.mouse.click(box.left + box.width / 2, box.top + box.height / 2);
}

export async function typeInto(page, selector, text, { clear = true } = {}) {
  await humanClick(page, selector);
  if (clear) {
    await page.evaluate((sel) => {
      const el = document.querySelector(sel);
      if (el) {
        el.value = '';
        el.dispatchEvent(new Event('input', { bubbles: true }));
      }
    }, selector);
  }
  await page.keyboard.type(text, { delay: 8 });
}

export async function waitFor(page, fn, { timeout = 10000, interval = 100, label = 'condition' } = {}) {
  const deadline = Date.now() + timeout;
  let last;
  while (Date.now() < deadline) {
    try {
      last = await page.evaluate(fn);
      if (last) return last;
    } catch (error) {
      last = error.message;
    }
    await new Promise((r) => setTimeout(r, interval));
  }
  throw new Error(`timed out waiting for ${label} (last: ${JSON.stringify(last)})`);
}

/** Navigate the app the way a user does: click the sidebar/link, not location.hash. */
export async function goTo(page, pageName, section) {
  if (pageName === 'settings' && section) {
    await page.evaluate((sec) => {
      location.hash = `#/settings:${sec}`;
    }, section);
  } else {
    await page.evaluate((name) => {
      location.hash = `#/${name}`;
    }, pageName);
  }
  await page.waitForFunction(
    (name) => {
      const el = document.querySelector(`#page-${name}`);
      return el && !el.classList.contains('hidden');
    },
    { timeout: 15000 },
    pageName
  );
  await new Promise((r) => setTimeout(r, 250));
}
