/* Archx Agent — incremental block renderer (1.7.0)
 *
 * WHY THIS EXISTS
 * The old streaming painter replaced `msg-content.innerHTML` wholesale every
 * ~50 ms. That destroyed every <pre> / table / reasoning scroller on each
 * paint, which caused all of:
 *   - code blocks you could not scroll while tokens were arriving (the
 *     scrollbar element was recreated under your pointer → "blinking"),
 *   - generated code showing its FIRST line instead of following the newest
 *     output,
 *   - the reasoning box jumping / losing its scroll position,
 *   - O(full-message) markdown+highlight work per paint (CPU hog).
 *
 * HOW IT WORKS
 * The message source is split into top-level chunks (code fences and tables
 * become their own chunk; prose between them is one chunk). Each chunk is
 * rendered once into a stable wrapper element. On later paints:
 *   - chunk source unchanged  → wrapper is NOT touched (scrollbars keep their
 *     identity, drags survive, zero work),
 *   - chunk source changed    → if it is a code block we patch only the
 *     <code> innerHTML inside the existing <pre> (scroll surface survives);
 *     otherwise the wrapper's innerHTML is replaced,
 *   - the actively growing chunk auto-follows its bottom edge (shows the
 *     latest code) unless the user scrolled up inside it — scrolling back to
 *     the bottom re-arms following, exactly like mainstream chat UIs.
 */

import { renderMarkdown, decorateCode, decorateTables, extractTables } from './markdown.js';
import { closeUnfinishedFence } from './markdown-stream.mjs';

const FOLLOW_THRESHOLD = 24; // px from bottom that still counts as "at bottom"

export const atBottom = (el) => el.scrollHeight - el.scrollTop - el.clientHeight <= FOLLOW_THRESHOLD;

/* follow-state lives per element, not per paint: a scroller follows its
   bottom edge until the user scrolls up; returning to the bottom re-arms. */
const followState = new WeakMap();
const boundScrollers = new WeakSet();

function bindFollow(el) {
  if (boundScrollers.has(el)) return;
  boundScrollers.add(el);
  el.addEventListener('scroll', () => { followState.set(el, atBottom(el)); }, { passive: true });
}
export function follows(el) { return followState.get(el) !== false; }
export function setFollows(el, on) { followState.set(el, on); }
function followScroll(el) {
  if (!el) return;
  bindFollow(el);
  if (followState.get(el) === false) return;
  el.scrollTop = el.scrollHeight;
}

/* ── chunking ─────────────────────────────────────────────── */
function isSeparatorLine(line) {
  let t = String(line).trim();
  if (t.startsWith('|')) t = t.slice(1);
  if (t.endsWith('|') && !t.endsWith('\\|')) t = t.slice(0, -1);
  const cells = t.split('|').map((c) => c.trim());
  return cells.length >= 1 && cells.every((c) => /^:?-{1,}:?$/.test(c) && c.length > 0);
}

/**
 * Split markdown source into chunks. Fences and tables become standalone
 * chunks (they own scroll surfaces); everything between them is grouped into
 * prose chunks. Unterminated fences stay open so the active code block keeps
 * growing inside the same chunk.
 */
export function splitBlocks(src) {
  const lines = String(src || '').split(/\r?\n/);
  const blocks = [];
  let buf = [];
  let fence = null;
  const flush = () => {
    if (buf.length) {
      const text = buf.join('\n');
      if (text.trim()) blocks.push(text);
      buf = [];
    }
  };
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const fm = line.match(/^\s*(```+|~~~+)/);
    if (fence) {
      buf.push(line);
      if (new RegExp(`^\\s*${fence.char}{${fence.len},}\\s*$`).test(line)) fence = null;
      continue;
    }
    if (fm) {
      flush();
      fence = { char: fm[1][0], len: fm[1].length };
      buf.push(line);
      continue;
    }
    if (line.includes('|') && i + 1 < lines.length && isSeparatorLine(lines[i + 1])) {
      flush();
      const rows = [line, lines[i + 1]];
      i += 2;
      while (i < lines.length && lines[i].trim() && lines[i].includes('|')) { rows.push(lines[i]); i += 1; }
      blocks.push(rows.join('\n'));
      continue;
    }
    if (!line.trim()) { flush(); continue; }
    buf.push(line);
  }
  flush();
  return blocks;
}

/* ── per-element registry ─────────────────────────────────── */
const registries = new WeakMap();
function registry(el) {
  let r = registries.get(el);
  if (!r) {
    r = { srcs: [], nodes: [], thinking: null, caret: null };
    registries.set(el, r);
  }
  return r;
}

const countOf = (root, sel) => root.querySelectorAll(sel).length;

function makeWrapper(html) {
  const wrap = document.createElement('div');
  wrap.className = 'md-block';
  wrap.innerHTML = html;
  decorateCode(wrap);
  decorateTables(wrap);
  return wrap;
}

/** Patch an existing wrapper whose chunk source changed. */
function patchWrapper(wrap, html, { active }) {
  const hadSingleCode = wrap.children.length === 1 && wrap.firstElementChild.classList.contains('codeblock');
  const probe = document.createElement('div');
  probe.innerHTML = html;
  decorateCode(probe);
  decorateTables(probe);
  const hasSingleCode = probe.children.length === 1 && probe.firstElementChild.classList.contains('codeblock');

  if (hadSingleCode && hasSingleCode) {
    // Keep the existing .codeblock/<pre> identity: only swap highlighted
    // code + language label, then follow the newest line.
    const oldBlock = wrap.firstElementChild;
    const newBlock = probe.firstElementChild;
    const oldPre = oldBlock.querySelector('pre');
    const newPre = newBlock.querySelector('pre');
    const oldHead = oldBlock.querySelector('.cb-head span');
    const newHead = newBlock.querySelector('.cb-head span');
    if (oldHead && newHead && oldHead.textContent !== newHead.textContent) oldHead.textContent = newHead.textContent;
    if (oldPre && newPre) {
      const code = oldPre.querySelector('code');
      const newCode = newPre.querySelector('code');
      if (code && newCode && code.innerHTML !== newCode.innerHTML) {
        code.innerHTML = newCode.innerHTML;
        code.className = newCode.className;
      }
      // followScroll() no-ops once the reader scrolled up, so calling it on
      // every changed paint is safe — and required: the closing fence and the
      // last code piece can land on the final (non-streaming) paint, and
      // gating on `active` left the view a few hundred px short.
      followScroll(oldPre);
    }
    return;
  }
  const scrollables = [...wrap.querySelectorAll('pre, .table-wrap')].map((n) => ({ n, top: n.scrollTop, left: n.scrollLeft, bottom: atBottom(n) }));
  wrap.replaceChildren(...probe.childNodes);
  const next = [...wrap.querySelectorAll('pre, .table-wrap')];
  scrollables.forEach((s, i) => {
    const el = next[i];
    if (!el) return;
    el.scrollLeft = s.left;
    el.scrollTop = s.bottom ? el.scrollHeight : Math.min(s.top, Math.max(0, el.scrollHeight - el.clientHeight));
  });
}

function ensureThinking(el, r, msg, streaming) {
  const want = !!msg.reasoning;
  if (!want) {
    if (r.thinking) { r.thinking.remove(); r.thinking = null; }
    return;
  }
  let d = r.thinking;
  if (!d || !d.isConnected) {
    d = document.createElement('details');
    d.className = 'thinking';
    d.innerHTML = '<summary><span class="spark">✦</span><span class="thinking-label">Thinking…</span></summary><div class="thinking-body"></div>';
    // User toggling the panel wins over the streaming auto-open. Programmatic
    // open/close changes also fire `toggle`, so they consume a credit from
    // _prog instead of being mistaken for the user.
    d._prog = 0;
    d.addEventListener('toggle', () => {
      if (d._prog > 0) { d._prog -= 1; return; }
      d.dataset.userToggled = '1';
    });
    r.thinking = d;
    el.insertBefore(d, el.firstChild);
  }
  const label = d.querySelector('.thinking-label');
  const wantLabel = streaming ? 'Thinking…' : 'Reasoning';
  if (label.textContent !== wantLabel) label.textContent = wantLabel;
  const body = d.querySelector('.thinking-body');
  if (body.textContent !== msg.reasoning) body.textContent = msg.reasoning;
  const setOpen = (v) => {
    if (d.open === v) return;
    d._prog = (d._prog || 0) + 1;
    d.open = v;
  };
  if (streaming) {
    if (d.dataset.userToggled !== '1') setOpen(true);
    followScroll(body);
  } else if (d.dataset.userToggled !== '1') {
    setOpen(false);
  }
}

function ensureCaret(el, r, on) {
  if (on && !r.caret) {
    const c = document.createElement('span');
    c.className = 'caret';
    r.caret = c;
    el.appendChild(c);
  } else if (!on && r.caret) {
    r.caret.remove();
    r.caret = null;
  }
  if (r.caret && el.lastChild !== r.caret) el.appendChild(r.caret);
}

/**
 * Incrementally paint one message body.
 * @param {HTMLElement} el   the .msg-content element
 * @param {{content:string, reasoning?:string, pending?:boolean}} msg
 */
export function paintBlocks(el, msg) {
  const r = registry(el);
  const streaming = !!msg.pending;
  const source = closeUnfinishedFence(String(msg.content || ''));
  const blocks = splitBlocks(source);

  ensureThinking(el, r, msg, streaming);

  for (let i = 0; i < blocks.length; i += 1) {
    const src = blocks[i];
    if (r.srcs[i] === src) continue;
    const active = i === blocks.length - 1;
    const html = renderMarkdown(src);
    const existing = r.nodes[i];
    if (existing && existing.isConnected) {
      // `active` here means "streaming paint": a changed block re-follows its
      // bottom edge whenever the reader was following, regardless of whether
      // the block is still the last one.
      patchWrapper(existing, html, { active: streaming });
    } else {
      const wrap = makeWrapper(html);
      const placeholder = r.nodes[i];
      if (placeholder && placeholder.isConnected) placeholder.replaceWith(wrap);
      else el.insertBefore(wrap, r.caret || null);
      r.nodes[i] = wrap;
      if (active && streaming) wrap.querySelectorAll('pre, .table-wrap').forEach(followScroll);
    }
    r.srcs[i] = src;
  }
  // shrink: message got shorter (edit/regenerate paths re-create the element,
  // but be safe anyway)
  if (r.nodes.length > blocks.length) {
    for (let i = blocks.length; i < r.nodes.length; i += 1) {
      if (r.nodes[i] && r.nodes[i].isConnected) r.nodes[i].remove();
    }
    r.nodes.length = blocks.length;
    r.srcs.length = blocks.length;
  }

  ensureCaret(el, r, streaming);
}

/** Drop cached state (used when an element is recycled for another message). */
export function resetBlocks(el) {
  registries.delete(el);
}

/** Cheap structural sanity used by tests. */
export function blockCount(el) {
  const r = registries.get(el);
  return r ? r.nodes.filter((n) => n.isConnected).length : 0;
}

export { countOf };
