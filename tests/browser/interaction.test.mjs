/*
 * Interaction tests — the chat flow through the UI itself.
 *
 * These only use real input: mouse.move/click at coordinates and keyboard.type.
 * Calling el.click() from the page would pass even when a control is covered
 * by an overlay, which is the exact failure class this suite exists to catch.
 */
import test from 'node:test';
import { Report, ok, equal } from '../helpers/assertions.mjs';
import { startApp, client } from '../helpers/app.mjs';
import { createMockUpstream } from '../mock-upstream/server.mjs';
import {
  launchBrowser,
  openPage,
  humanClick,
  typeInto,
  waitFor,
  isHittable,
  goTo,
  loadPuppeteer,
  ARTIFACT_ROOT,
  VIEWPORTS,
} from './support.mjs';
import { writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';

const PUPPETEER_ENABLED = process.env.BROWSER_TESTS === '1' || process.env.CI === 'true';

let app;
let mock;
let browser;
let mockBase;
const report = new Report('interaction');

test.before(async () => {
  if (!PUPPETEER_ENABLED) return;
  mock = createMockUpstream();
  const mockPort = await mock.listen();
  mockBase = `http://127.0.0.1:${mockPort}`;
  app = await startApp();
  const api = client(app.baseUrl);
  await api.addProvider({ name: 'Mock Provider', baseUrl: `${mockBase}/v1`, model: 'mock-chat' });
  browser = await launchBrowser(loadPuppeteer());
});

test.after(async () => {
  await browser?.close();
  await app?.stop();
  await mock?.close();
  await mkdir(ARTIFACT_ROOT, { recursive: true });
  await writeFile(path.join(ARTIFACT_ROOT, 'interaction.json'), JSON.stringify(report.toJSON(), null, 2));
});

const setScenario = (body) =>
  fetch(`${mockBase}/control/scenario`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });

async function send(message, session) {
  const { page } = session;
  await humanClick(page, '#input');
  await page.keyboard.type(message, { delay: 5 });
  await humanClick(page, '#btn-send');
}

async function waitForAnswer(page, expected, timeout = 25000) {
  return waitFor(
    page,
    (want) => {
      const rows = Array.from(document.querySelectorAll('#messages .msg'));
      const last = rows[rows.length - 1];
      if (!last) return false;
      const text = last.innerText || '';
      return text.includes(want) ? text : false;
    },
    { timeout, label: `an answer containing "${expected}"` },
    expected
  );
}

test('typing a message and sending it streams an answer into the chat', { skip: !PUPPETEER_ENABLED }, async () => {
  const session = await openPage(browser, app.baseUrl, VIEWPORTS.desktop);
  await report.run('send-flow', 'message round-trip through the composer', async () => {
    await setScenario({ chunks: ['Streaming ', 'works ', 'end ', 'to ', 'end.'] });
    await send('hello from the test', session);
    const text = await waitForAnswer(session.page, 'end.');
    ok(text.includes('Streaming works end to end.'), 'the full answer rendered');

    const cleared = await session.page.$eval('#input', (el) => el.value);
    equal(cleared, '', 'composer cleared as soon as the message was sent');

    const userRow = await session.page.evaluate(() =>
      Array.from(document.querySelectorAll('#messages .msg')).map((m) => m.innerText).join('\n')
    );
    ok(userRow.includes('hello from the test'), 'the user message is in the transcript');
    await session.fullShot('interaction-01-answer');
  });
  await session.close();
});

test('send button is disabled/blocked while the cursor has no text', { skip: !PUPPETEER_ENABLED }, async () => {
  const session = await openPage(browser, app.baseUrl, VIEWPORTS.laptop);
  await report.run('empty-send', 'empty composer does not send', async () => {
    const hit = await isHittable(session.page, '#btn-send');
    ok(hit.found, 'send button exists');
    await humanClick(session.page, '#btn-send');
    await new Promise((r) => setTimeout(r, 300));
    const rows = await session.page.$$eval('#messages .msg', (els) => els.length);
    ok(rows <= 2, `no extra empty message was created (rows: ${rows})`);
  });
  await session.close();
});

test('stop button interrupts a slow stream and keeps what arrived', { skip: !PUPPETEER_ENABLED }, async () => {
  const session = await openPage(browser, app.baseUrl, VIEWPORTS.desktop);
  await report.run('stop-stream', 'stop halts generation without losing partial text', async () => {
    await setScenario({ chunks: ['one ', 'two ', 'three ', 'four ', 'five ', 'six ', 'seven ', 'eight '], delayMs: 400 });
    await send('slow answer please', session);
    await waitForAnswer(session.page, 'one', 20000);
    const stopVisible = await session.page.$eval('#btn-stop', (el) => !el.classList.contains('hidden'));
    ok(stopVisible, 'stop button appears while generating');
    await humanClick(session.page, '#btn-stop');
    await waitFor(session.page, () => document.querySelector('#btn-stop').classList.contains('hidden'), {
      label: 'stop button to disappear',
      timeout: 8000,
    });
    const partial = await session.page.evaluate(() => {
      const rows = document.querySelectorAll('#messages .msg');
      return rows[rows.length - 1].innerText;
    });
    ok(partial.length > 0, 'partial answer is kept on screen');
    ok(!partial.includes('eight'), 'generation really stopped before the end');
    await setScenario({});
  });
  await session.close();
});

test('markdown answer renders headings, lists, tables and code blocks', { skip: !PUPPETEER_ENABLED }, async () => {
  const session = await openPage(browser, app.baseUrl, VIEWPORTS.desktop);
  await report.run('markdown', 'rich markdown renders as real elements', async () => {
    const answer = [
      '## Result',
      '',
      'A short list:',
      '',
      '- alpha',
      '- beta',
      '',
      '| name | value |',
      '| --- | --- |',
      '| a | 1 |',
      '',
      '```js',
      'const answer = 42;',
      '```',
    ].join('\n');
    await setScenario({ chunks: answer.match(/.{1,40}/gs), delayMs: 10 });
    await send('show me markdown', session);
    await waitForAnswer(session.page, 'const answer = 42;');
    await new Promise((r) => setTimeout(r, 900));

    const found = await session.page.evaluate(() => {
      const last = document.querySelectorAll('#messages .msg');
      const row = last[last.length - 1];
      return {
        h2: !!row.querySelector('h2, h3'),
        list: row.querySelectorAll('li').length,
        table: !!row.querySelector('table'),
        code: !!row.querySelector('pre code, pre'),
        rawTablePipes: row.innerText.includes('| --- |'),
      };
    });
    ok(found.h2, 'heading rendered');
    ok(found.list >= 2, `list items rendered (${found.list})`);
    ok(found.table, 'table rendered');
    ok(found.code, 'code block rendered');
    ok(!found.rawTablePipes, 'markdown source is not shown raw');
    await session.fullShot('interaction-02-markdown');
  });
  await session.close();
});

test('code block can be scrolled and keeps its position during streaming', { skip: !PUPPETEER_ENABLED }, async () => {
  const session = await openPage(browser, app.baseUrl, VIEWPORTS.desktop);
  await report.run('code-scroll', 'streaming code block keeps scroll position', async () => {
    const lines = Array.from({ length: 80 }, (_, i) => `const line${i} = ${i};`).join('\n');
    await setScenario({ chunks: lines.match(/.{1,60}/gs), delayMs: 25 });
    await send('write a long code file', session);
    await waitForAnswer(session.page, 'const line0', 20000);
    await new Promise((r) => setTimeout(r, 700));

    const box = await session.page.evaluate(() => {
      const pres = Array.from(document.querySelectorAll('#messages pre'));
      const pre = pres[pres.length - 1];
      if (!pre) return null;
      pre.scrollTop = 0;
      return { scrollHeight: pre.scrollHeight, clientHeight: pre.clientHeight, top: pre.scrollTop };
    });
    ok(box, 'a code block exists');
    ok(box.scrollHeight > box.clientHeight + 20, 'code block actually overflows (so scrolling is meaningful)');

    await new Promise((r) => setTimeout(r, 1200));
    const after = await session.page.evaluate(() => {
      const pres = Array.from(document.querySelectorAll('#messages pre'));
      const pre = pres[pres.length - 1];
      return pre ? pre.scrollTop : null;
    });
    // 1.7.0 fixed a full re-render that reset this to 0 on every paint.
    ok(after === 0, `scrolling up is respected while the answer streams (scrollTop ${after})`);
    await setScenario({});
  });
  await session.close();
});

test('theme switch repaints immediately and survives a reload', { skip: !PUPPETEER_ENABLED }, async () => {
  const session = await openPage(browser, app.baseUrl, VIEWPORTS.desktop);
  await report.run('theme-persist', 'theme choice persists across reload', async () => {
    await goTo(session.page, 'settings', 'general');
    await humanClick(session.page, '[data-theme-choice="light"]');
    await waitFor(session.page, () => document.documentElement.dataset.theme === 'light', { label: 'light theme' });
    await session.page.reload({ waitUntil: 'networkidle2' });
    await session.page.waitForSelector('#input');
    const afterReload = await session.page.evaluate(() => document.documentElement.dataset.theme);
    equal(afterReload, 'light', 'theme survives a reload');
    await goTo(session.page, 'settings', 'general');
    await humanClick(session.page, '[data-theme-choice="dark"]');
  });
  await session.close();
});

test('chat appears in the sidebar and switching keeps both transcripts', { skip: !PUPPETEER_ENABLED }, async () => {
  const session = await openPage(browser, app.baseUrl, VIEWPORTS.desktop);
  await report.run('sidebar-switch', 'sidebar lists chats and switching preserves them', async () => {
    await setScenario({ chunks: ['First ', 'chat ', 'answer.'] });
    await send('chat number one', session);
    await waitForAnswer(session.page, 'First chat answer.');

    await humanClick(session.page, '#new-chat');
    await setScenario({ chunks: ['Second ', 'chat ', 'answer.'] });
    await send('chat number two', session);
    await waitForAnswer(session.page, 'Second chat answer.');

    const titles = await session.page.$$eval('#chat-list .chat-item, #chat-list [data-chat-id]', (els) =>
      els.map((el) => el.innerText.trim()).filter(Boolean)
    );
    ok(titles.length >= 2, `sidebar shows both chats (${titles.length})`);

    const items = await session.page.$$('#chat-list .chat-item, #chat-list [data-chat-id]');
    await items[items.length - 1].click();
    await new Promise((r) => setTimeout(r, 500));
    const text = await session.page.evaluate(() => document.querySelector('#messages').innerText);
    ok(text.includes('chat number one'), 'switching back restores the older transcript');
    await session.fullShot('interaction-03-two-chats');
  });
  await session.close();
});

test('keyboard: Enter sends, Shift+Enter adds a line', { skip: !PUPPETEER_ENABLED }, async () => {
  const session = await openPage(browser, app.baseUrl, VIEWPORTS.desktop);
  await report.run('keyboard', 'Enter sends; Shift+Enter keeps a newline', async () => {
    await setScenario({ chunks: ['Keyboard ', 'answer.'] });
    await humanClick(session.page, '#input');
    await session.page.keyboard.type('first line');
    await session.page.keyboard.down('Shift');
    await session.page.keyboard.press('Enter');
    await session.page.keyboard.up('Shift');
    await session.page.keyboard.type('second line');
    const multiline = await session.page.$eval('#input', (el) => el.value);
    ok(multiline.includes('\n'), 'Shift+Enter inserted a newline instead of sending');

    await session.page.keyboard.press('Enter');
    await waitForAnswer(session.page, 'Keyboard answer.');
    const sent = await session.page.evaluate(() => document.querySelector('#messages').innerText);
    ok(sent.includes('first line'), 'Enter sent the message');
  });
  await session.close();
});

test('mobile: sidebar drawer opens and closes, composer stays usable', { skip: !PUPPETEER_ENABLED }, async () => {
  const session = await openPage(browser, app.baseUrl, VIEWPORTS.mobile);
  await report.run('mobile-drawer', 'drawer and composer work at 390 px', async () => {
    await session.shot('interaction-04-mobile-closed');
    await humanClick(session.page, '#side-toggle');
    await waitFor(session.page, () => !document.querySelector('#sidebar').classList.contains('hidden'), {
      label: 'sidebar to open',
    });
    await session.shot('interaction-05-mobile-open');
    await humanClick(session.page, '#side-toggle');
    await waitFor(session.page, () => document.querySelector('#sidebar').classList.contains('hidden'), {
      label: 'sidebar to close',
    });

    const composer = await isHittable(session.page, '#input');
    ok(composer.hittable, `composer is clickable on mobile (${composer.reason || 'ok'})`);
    const send = await isHittable(session.page, '#btn-send');
    ok(send.hittable, `send is clickable on mobile (${send.reason || 'ok'})`);

    await setScenario({ chunks: ['Mobile ', 'works.'] });
    await send2(session);
    await waitForAnswer(session.page, 'Mobile works.');
    await session.shot('interaction-06-mobile-answer');
  });
  await session.close();
});

async function send2(session) {
  await humanClick(session.page, '#input');
  await session.page.keyboard.type('hello from a phone');
  await humanClick(session.page, '#btn-send');
}

test('every visible interactive element is reachable at three viewports', { skip: !PUPPETEER_ENABLED }, async () => {
  const states = [
    ['chat', null],
    ['studio', null],
    ['memory', null],
    ['debug', null],
    ['settings', 'general'],
    ['settings', 'providers'],
    ['settings', 'models'],
    ['settings', 'danger'],
  ];

  for (const [name, viewport] of Object.entries(VIEWPORTS)) {
    for (const [pageName, section] of states) {
      await report.run(`hit-${name}-${pageName}${section ? '-' + section : ''}`, `hit-test ${pageName}${section ? ':' + section : ''} @ ${name}`, async () => {
        const session = await openPage(browser, app.baseUrl, viewport);
        try {
          await goTo(session.page, pageName, section);
          const blocked = await session.page.evaluate(() => {
            const selector =
              'button:not([disabled]), a[href], input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea:not([disabled]), [role=button]';
            const out = [];
            for (const el of document.querySelectorAll(selector)) {
              const style = getComputedStyle(el);
              if (style.visibility === 'hidden' || style.display === 'none') continue;
              if (Number(style.opacity) === 0) continue;
              const box = el.getBoundingClientRect();
              if (box.width < 2 || box.height < 2) continue;
              if (box.bottom < 0 || box.top > innerHeight) continue; // scrolled out of view is fine
              const x = box.left + box.width / 2;
              const y = box.top + box.height / 2;
              if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) continue;
              const hit = document.elementFromPoint(x, y);
              if (!hit) continue;
              const reaches = hit === el || el.contains(hit) || hit.contains(el);
              // a label wrapping its input is legitimate
              const labelled = el.closest('label') && el.closest('label').contains(hit);
              if (!reaches && !labelled) {
                out.push({
                  tag: el.tagName.toLowerCase(),
                  id: el.id,
                  cls: String(el.className).split(' ').slice(0, 2).join(' '),
                  coveredBy: hit ? hit.tagName.toLowerCase() + '.' + String(hit.className).split(' ')[0] : 'nothing',
                });
              }
            }
            return out;
          });
          ok(blocked.length === 0, `${blocked.length} blocked control(s): ${JSON.stringify(blocked.slice(0, 5))}`);
        } finally {
          await session.close();
        }
      });
    }
  }
});

test('interaction suite had no failures', { skip: !PUPPETEER_ENABLED }, async () => {
  const failed = report.failed;
  const summary = failed.map((c) => `${c.id}: ${c.message}`).join('\n');
  ok(failed.length === 0, `${failed.length} interaction check(s) failed\n${summary}`);
});
