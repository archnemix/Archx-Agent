'use strict';

/*
 * Free web search (1.8.0) — inspired by delef/dsh-free-web-search.
 * Keyless engines with an automatic fallback chain, in user-configured
 * priority order. Every engine returns [{title,url,snippet}].
 */

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36';

const decodeEntities = (s) =>
  String(s || '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&#x27;/g, "'")
    .replace(/&#(\d+);/g, (_, n) => { try { return String.fromCodePoint(Number(n)); } catch { return ''; } })
    .replace(/&apos;/g, "'");

const stripTags = (s) => decodeEntities(String(s || '').replace(/<[^>]*>/g, ''));

function composeTimeout(ms) {
  const ctrl = new AbortController();
  setTimeout(() => ctrl.abort(new Error('timeout')), ms);
  return ctrl.signal;
}

async function getText(url, { timeoutMs = 12000, headers = {} } = {}) {
  const res = await fetch(url, {
    headers: { 'User-Agent': UA, Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8', 'Accept-Language': 'en-US,en;q=0.9', ...headers },
    redirect: 'follow',
    signal: composeTimeout(timeoutMs),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`.trim());
  return res.text();
}

/* ── DuckDuckGo HTML ─────────────────────────────────────────── */
async function searchDuckDuckGo(query, maxResults) {
  const html = await getText(`https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`);
  const out = [];
  const re = /<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>[\s\S]*?(?:<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)<\/a>|<div[^>]+class="result__snippet"[^>]*>([\s\S]*?)<\/div>)/g;
  let m;
  while ((m = re.exec(html)) && out.length < maxResults) {
    let url = decodeEntities(m[1]);
    // DDG wraps outbound links in //duckduckgo.com/l/?uddg=...
    const uddg = /uddg=([^&]+)/.exec(url);
    if (uddg) { try { url = decodeURIComponent(uddg[1]); } catch {} }
    const title = stripTags(m[2]).trim();
    const snippet = stripTags(m[3] || m[4] || '').trim();
    if (title && url.startsWith('http')) out.push({ title, url, snippet });
  }
  if (!out.length) throw new Error('DuckDuckGo returned no parsable results.');
  return out;
}

/* ── Bing ────────────────────────────────────────────────────── */
function unwrapBingUrl(url) {
  // Bing SERP hrefs are click-trackers: /ck/a?...&u=a1<base64url>
  const u = /[?&]u=([^&]+)/.exec(url || '');
  if (u) {
    try {
      const b64 = u[1].replace(/^a1/, '').replace(/-/g, '+').replace(/_/g, '/');
      const decoded = Buffer.from(b64, 'base64').toString('utf8');
      if (decoded.startsWith('http')) return decoded;
    } catch {}
  }
  return url;
}
async function searchBing(query, maxResults) {
  const html = await getText(`https://www.bing.com/search?q=${encodeURIComponent(query)}&count=${Math.min(20, maxResults * 2)}`, {
    headers: { Cookie: 'SRCHHPGUSR=NEWWND=0' },
  });
  const out = [];
  const re = /<li class="b_algo"[^>]*>([\s\S]*?)<\/li>/g;
  let m;
  while ((m = re.exec(html)) && out.length < maxResults) {
    const block = m[1];
    const a = /<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/.exec(block);
    if (!a) continue;
    let url = decodeEntities(a[1]);
    url = unwrapBingUrl(url);
    const title = stripTags(a[2]).trim();
    const snip = /<p[^>]*>([\s\S]*?)<\/p>/.exec(block.replace(a[0], ''));
    const snippet = stripTags(snip ? snip[1] : '').trim();
    if (title && url.startsWith('http')) out.push({ title, url, snippet });
  }
  if (!out.length) throw new Error('Bing returned no parsable results.');
  return out;
}

/* ── SearXNG (public instances) ──────────────────────────────── */
const SEARXNG_INSTANCES = [
  'https://searx.be',
  'https://search.bus-hit.me',
  'https://priv.au',
  'https://searx.tiekoetter.com',
];
async function searchSearXng(query, maxResults) {
  let lastErr = null;
  for (const inst of SEARXNG_INSTANCES) {
    try {
      const res = await fetch(`${inst}/search?q=${encodeURIComponent(query)}&format=json`, {
        headers: { 'User-Agent': UA, Accept: 'application/json' },
        signal: composeTimeout(10000),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      const json = await res.json();
      const results = (Array.isArray(json.results) ? json.results : []).slice(0, maxResults)
        .filter((r) => r && r.url && r.title)
        .map((r) => ({ title: stripTags(r.title), url: String(r.url), snippet: stripTags(r.content || '') }));
      if (results.length) return results;
      throw new Error('empty');
    } catch (err) { lastErr = err; }
  }
  throw lastErr || new Error('All SearXNG instances failed.');
}

const ENGINES = {
  ddg: { label: 'DuckDuckGo (free, no key)', run: searchDuckDuckGo },
  bing: { label: 'Bing (free, no key)', run: searchBing },
  searxng: { label: 'SearXNG public instances (free, no key)', run: searchSearXng },
};
const DEFAULT_PRIORITY = ['ddg', 'bing', 'searxng'];

async function webSearch(query, { engines, maxResults = 5 } = {}) {
  const order = Array.isArray(engines) && engines.length ? engines.filter((e) => ENGINES[e]) : DEFAULT_PRIORITY;
  const attempts = [];
  for (const id of order) {
    const t0 = Date.now();
    try {
      const results = await ENGINES[id].run(query, maxResults);
      return { ok: true, engine: id, results, attempts, ms: Date.now() - t0 };
    } catch (err) {
      attempts.push({ engine: id, error: String(err && err.message || err), ms: Date.now() - t0 });
    }
  }
  return { ok: false, engine: null, results: [], attempts, error: 'Every search engine in the chain failed.' };
}

async function testEngines() {
  const out = [];
  for (const id of Object.keys(ENGINES)) {
    const t0 = Date.now();
    try {
      const r = await ENGINES[id].run('archx agent test', 3);
      out.push({ engine: id, ok: true, count: r.length, ms: Date.now() - t0 });
    } catch (err) {
      out.push({ engine: id, ok: false, error: String(err && err.message || err), ms: Date.now() - t0 });
    }
  }
  return out;
}

module.exports = { webSearch, testEngines, ENGINES, DEFAULT_PRIORITY };
