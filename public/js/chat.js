/* Archx Agent — conversation engine v2: reasoning, per-provider completion */

import { $, toast, msNow } from './dom.js';
import * as api from './api.js';
import { applyChatFailure } from './chat-failure.mjs';
import { tableToCSV, tableToTSV, tableToJSON, tableToMarkdown, tableToHTML, downloadText } from './markdown.js';
import {
  state, activeChat, activeProvider, enabledPromptsFor, newChatRecord, touchChats, touchChat, recordChatDebug, addChatTraceId,
  pickInitialModel, visibleModelsFor, setActive,
} from './state.js';
import {
  renderMessages, renderSidebar, renderModelUI, paintContent, metaText,
  scrollBottom, setStreamingUI, setConn, setPinned, renderModelMenu, updateJumpBtn, appendLiveTool,} from './render.js';

/* 1.7.2: streams are per-chat, so several conversations can generate at the
   same time (like mainstream chat UIs). The UI indicators follow the chat
   you are looking at. */
const streams = new Map(); // chatId -> { controller, userStopped }
export const isStreaming = (chatId) => (chatId ? streams.has(chatId) : streams.size > 0);
function syncStreamingUI() {
  const cur = activeChat();
  setStreamingUI(!!(cur && streams.has(cur.id)));
}
export const refreshStreamingUI = syncStreamingUI;

/* ── smart model-list fetching (1.7.0) ───────────────────────
 * The live model list of a provider changes rarely, but the old UI re-POSTed
 * /models on every menu open / hover / settings visit. Now:
 *   - results are cached per provider with a 5-minute TTL,
 *   - concurrent requests for the same provider share ONE network call,
 *   - `{ force: true }` (refresh button, Fetch models action) bypasses both.
 * Fewer requests = less lag, less journal noise, less provider rate-limit risk. */
const MODEL_TTL_MS = 5 * 60 * 1000;
const modelCacheTs = new Map();
const modelInflight = new Map();

/** fetch the live model list of one provider into memory (never persisted) */
export async function fetchModelsFor(providerId, opts = {}) {
  const p = state.providers.find((x) => x.id === providerId);
  if (!p) return [];
  if (!opts.force && state.providerModels[providerId] && (Date.now() - (modelCacheTs.get(providerId) || 0)) < MODEL_TTL_MS) {
    return state.providerModels[providerId];
  }
  if (!opts.force && modelInflight.has(providerId)) return modelInflight.get(providerId);
  setConn('busy');
  const promise = (async () => {
    try {
      const body = await api.getProviderModels(providerId);
      const list = Array.isArray(body) ? body : (body.data || []);
      state.providerModels[providerId] = list;
      modelCacheTs.set(providerId, Date.now());
      if (!Array.isArray(p.models?.catalog) || p.models.catalogInitialized !== body.catalogInitialized || (Array.isArray(body.catalog) && JSON.stringify(body.catalog) !== JSON.stringify(p.models.catalog))) {
        if (body.catalog || body.catalogInitialized != null) {
          state.providers = state.providers.map((x) => x.id === providerId ? { ...x, models: { ...(x.models || {}), catalog: Array.isArray(body.catalog) ? body.catalog : (x.models?.catalog || []), catalogInitialized: body.catalogInitialized === true, selectionMode: body.selectionMode || x.models?.selectionMode || 'checklist' } } : x);
        }
      }
      /* 1.9.0: surfaces rendered before this fetch resolved stay stale —
         let the UI refill pickers (studio dropdowns, model menus). */
      window.dispatchEvent(new CustomEvent('archx:models-loaded', { detail: { providerId } }));
      if (state.active.providerId === providerId) {
        const pick = pickInitialModel(state.providers.find((x) => x.id === providerId) || p);
        if (pick && pick !== state.active.model) {
          state.active = await api.setActive({ providerId, model: pick });
        } else if (!pick && state.active.model) {
          state.active = await api.setActive({ providerId, model: null });
        }
      }
      renderModelUI();
      if (!opts.silent && document.querySelector('#model-menu') && !document.querySelector('#model-menu').classList.contains('hidden')) {
        renderModelMenu(providerId);
      }
      setConn('');
      return list;
    } catch (e) {
      setConn('err');
      // Built-in provider fallback: OpenRouter can still use openrouter/free even
      // when /models cannot be fetched (for example while offline or before auth).
      if (!state.active.model && p.defaultModel && visibleModelsFor(p).some(m => m.id === p.defaultModel)) {
        try { state.active = await api.setActive({ providerId, model: p.defaultModel }); renderModelUI(); } catch {}
      }
      if (!opts.silent) toast(e.message, 'err');
      if (p.defaultModel && visibleModelsFor(p).length) return state.providerModels[providerId] || visibleModelsFor(p);
      throw e;
    } finally {
      modelInflight.delete(providerId);
    }
  })();
  modelInflight.set(providerId, promise);
  return promise;
}

/* ── streaming paint (throttled to ~20fps to keep CPU low) ──
 * 1.7.0: the paint itself is now incremental (see blocks.js) — only the
 * actively growing markdown chunk is re-rendered, completed code blocks keep
 * their scroll position, and the visible viewport follows the newest output
 * until the reader scrolls up. */
const paints = new WeakMap();
function schedulePaint(el, msg) {
  if (paints.has(el)) return;
  const timer = setTimeout(() => {
    requestAnimationFrame(() => {
      paints.delete(el);
      if (!el.isConnected) return;
      paintContent(el, msg);
      scrollBottom(false);
      updateJumpBtn();
    });
  }, 50);
  paints.set(el, timer);
}


/* ── generation ──────────────────────────────────────────── */
export async function complete(chat) {
  const provider = activeProvider();
  const requestedModel = state.active.model;
  const debug = (category, label, detail) => recordChatDebug(category, label, detail, chat);
  if (!provider) {
    toast('Add a provider first (Settings → Providers).', 'err');
    return;
  }
  if (!requestedModel) return toast('Pick a model first (top-left dropdown).', 'err');
  debug('other', 'Chat request queued', { model: requestedModel, provider: provider.name });
  const msg = {
    role: 'assistant',
    content: '',
    reasoning: '',
    pending: true,
    ts: Date.now(),
    meta: { provider: provider.name, model: requestedModel },
  };
  chat.messages.push(msg);
  renderMessages();
  const msgIndex = chat.messages.length - 1;
  /* 1.7.0: the paint target is resolved per paint, so switching chats while
     a generation runs keeps streaming into the right record and repainting
     resumes automatically when the user comes back. */
  const liveContentEl = () => {
    const cur = activeChat();
    if (!cur || cur.id !== chat.id) return null;
    const row = document.querySelector(`#messages .msg-row[data-idx="${msgIndex}"]`);
    return row ? $('.msg-content', row) : null;
  };
  const controller = new AbortController();
  const ctl = { controller, userStopped: false };
  streams.set(chat.id, ctl);
  syncStreamingUI();
  // persist partial output periodically so a closed tab never loses a reply
  const persistTimer = setInterval(() => touchChat(chat), 1500);
  const t0 = msNow();

  const msgs = [];
  // 1.6.6 hot-switch: "stack" keeps earlier instructions and appends each extra
  // enabled prompt as another system message tagged `update:`; "replace" sends
  // only the primary prompt so the model never sees earlier wording.
  const mode = state.settings.systemPromptMode === 'replace' ? 'replace' : 'stack';
  const enabled = enabledPromptsFor(chat);
  if (mode === 'replace') {
    // one single first system message, merged — model never sees separate updates
    const merged = enabled.map((p) => (p.content || '').trim()).filter(Boolean).join('\n\n');
    if (merged) msgs.push({ role: 'system', content: merged });
  } else {
    enabled.forEach((p, i) => {
      const content = (p.content || '').trim();
      if (!content) return;
      msgs.push({ role: 'system', content: i === 0 ? content : `update: ${content}` });
    });
  }
  if (enabled.length) {
    debug('api', 'System prompts included', {
      mode,
      systemPromptId: enabled[0].id,
      prompts: enabled.map((p, i) => ({ id: p.id, name: p.name, role: 'system', tag: mode === 'stack' && i > 0 ? 'update' : null, chars: (p.content || '').trim().length })),
    });
  } else {
    debug('api', 'No system prompt', { systemPromptId: null, mode, reason: 'all prompts unchecked' });
  }
  chat.messages.slice(0, -1).forEach((m) => msgs.push({ role: m.role, content: m.content }));

  let usage = null;
  try {
    const text = await api.chat(
      {
        providerId: provider.id,
        model: requestedModel,
        messages: msgs,
        stream: !!state.settings.stream,
        temperature: state.settings.temperature,
        maxTokens: state.settings.maxTokens || null,
        chatId: chat.id,
        modeId: chat.modeId || 'simple-chat',
        profileId: state.settings.advancedProfiles ? state.activeProfileId : null,
        systemPromptId: enabled[0]?.id || null,
        useWebSearch: state.webSearchOn === true, // 1.8.0 web search tool
      },
      controller.signal,
      {
        onDelta: (delta) => {
          msg.content += delta;
          const el = liveContentEl();
          if (el) schedulePaint(el, msg);
        },
        onTool: (tool) => {
          msg.tools = msg.tools || [];
          msg.tools.push(tool);
          const row = liveContentEl()?.closest('.msg-row');
          if (row) appendLiveTool(row, tool);
          debug('tools', tool.kind === 'web-search' ? `Web search · ${tool.engine || 'failed'} · ${tool.results ? tool.results.length + ' sources' : tool.error || ''}` : `Read page · ${tool.title || tool.url || tool.error}`, tool);
        },
        onReasoning: (r) => {
          msg.reasoning += r;
          const el = liveContentEl();
          if (el) schedulePaint(el, msg);
        },
        onMeta: (meta) => {
          if (!meta) return;
          if (meta.usage) usage = meta.usage;
          if (meta.provider) msg.meta.provider = meta.provider;
          if (meta.providerId) msg.meta.providerId = meta.providerId;
          if (meta.model) msg.meta.model = meta.model;
          if (meta.profileId) msg.meta.profileId = meta.profileId;
          if (meta.fallbackIndex != null) msg.meta.fallbackIndex = meta.fallbackIndex;
          if (meta.fallbackUsed) msg.meta.fallbackUsed = true;
          if (meta.traceId) { msg.meta.traceId = meta.traceId; addChatTraceId(meta.traceId, chat); }
          if (meta.object === 'archx.fallback') { msg.meta.fallbackUsed = true; msg.meta.fallbackAttempt = meta; debug('api', 'Provider failed · fallback starting', meta); }
        },
      }
    );
    msg.pending = false;
    if (text) msg.content = text;
    const ms = Math.round(msNow() - t0);
    const completionTokens = usage && (usage.completion_tokens != null ? usage.completion_tokens : usage.output_tokens);
    msg.meta = {
      ...msg.meta,
      provider: msg.meta.provider || provider.name,
      model: msg.meta.model || requestedModel,
      ms,
      tps: completionTokens && ms > 0 ? Math.round(completionTokens / (ms / 1000)) : null,
    };
    if (msg.meta.fallbackUsed) debug('api', 'Fallback used', { provider: msg.meta.provider, model: msg.meta.model, fallbackIndex: msg.meta.fallbackIndex });
  } catch (err) {
    msg.pending = false;
    const ms = Math.round(msNow() - t0);
    if ((err && err.name === 'AbortError') || ctl.userStopped) {
      applyChatFailure(msg, err, { stopped: true, elapsed: ms });
    } else {
      applyChatFailure(msg, err, { elapsed: ms });
      debug('api', 'Chat request failed', { error: msg.errorMessage });
      setConn('err');
    }
  } finally {
    streams.delete(chat.id);
    clearInterval(persistTimer);
    syncStreamingUI();
    touchChat(chat);
    // 1.7.0: navigating away during a generation is allowed (the stream keeps
    // writing to its own chat, like mainstream chat UIs). Only repaint/focus
    // when the finished chat is still the one on screen — and repaint IN
    // PLACE: a full renderMessages() here rebuilt the DOM and threw away the
    // reader's scroll position (code block jumped to top exactly when the
    // answer finished).
    if (activeChat() && activeChat().id === chat.id) {
      const row = document.querySelector(`#messages .msg-row[data-idx="${msgIndex}"]`);
      if (row) {
        $('.msg-meta', row).textContent = metaText(msg);
        $('.msg', row).classList.toggle('error', !!msg.error);
        paintContent($('.msg-content', row), msg);
        scrollBottom(false);
        updateJumpBtn();
      } else {
        renderMessages();
      }
      $('#input').focus();
    } else {
      renderSidebar();
    }
  }
}

export async function sendUser(text) {
  text = (text || '').trim();
  if (!text) return false;
  if (!activeProvider()) { toast('No provider configured — add one first.', 'err'); return false; }
  let chat = activeChat();
  if (!chat) chat = newChatRecord();
  if (streams.has(chat.id)) { toast('This chat is still generating — stop it first, or send from another chat.', 'err'); return false; }
  if (!chat.messages.length) {
    chat.title = text.length > 42 ? text.slice(0, 42) + '…' : text;
    renderSidebar();
  }
  chat.messages.push({ role: 'user', content: text, ts: Date.now() });
  touchChat(chat);
  renderMessages();
  // 1.7.1: the composer clears the moment the message is sent, not when the
  // reply finishes — the old `.then()` after complete() kept your text on
  // screen for the whole generation.
  const inp = $('#input');
  if (inp) { inp.value = ''; inp.style.height = 'auto'; }
  await complete(chat);
  return true;
}

export function regenerate(idx) {
  const chat = activeChat();
  if (!chat || streams.has(chat.id)) return;
  archiveBranch(chat, idx, 'regenerate');
  chat.messages.length = idx;
  touchChat(chat);
  renderMessages();
  complete(chat);
}

export function stop(chatId) {
  // click handlers pass the MouseEvent as first argument — ignore non-strings
  const id = typeof chatId === 'string' ? chatId : (activeChat() && activeChat().id);
  const ctl = id ? streams.get(id) : null;
  if (!ctl) return;
  ctl.userStopped = true;
  ctl.controller.abort();
}

/* ── branches (1.7.2) ─────────────────────────────────────────
   Editing or regenerating no longer destroys the old continuation: the
   discarded tail is archived as a branch you can reopen later. Switching
   archives the current tail first, so no continuation is ever lost. */
export function archiveBranch(chat, at, origin) {
  const tail = chat.messages.slice(at);
  if (!tail.length) return null;
  if (!Array.isArray(chat.branches)) chat.branches = [];
  const branch = {
    id: 'b-' + Math.random().toString(36).slice(2, 10),
    at,
    origin,
    ts: Date.now(),
    title: String((tail.find((m) => m.role === 'user') || tail[0])?.content || '').slice(0, 48),
    messages: tail,
  };
  chat.branches.push(branch);
  if (chat.branches.length > 24) chat.branches.splice(0, chat.branches.length - 24);
  touchChat(chat);
  return branch;
}

export function switchBranch(chat, branchId) {
  const idx = (chat.branches || []).findIndex((b) => b.id === branchId);
  if (idx < 0 || !chat || streams.has(chat.id)) return false;
  const branch = chat.branches[idx];
  archiveBranch(chat, branch.at, 'current');
  chat.branches.splice(idx, 1);
  chat.messages = chat.messages.slice(0, branch.at).concat(branch.messages);
  touchChat(chat);
  return true;
}

/* ── inline edit of a user message ───────────────────────── */
export function editUser(idx, row) {
  const chat = activeChat();
  if (!chat || streams.has(chat.id)) return;
  const m = chat.messages[idx];
  const content = $('.msg-content', row);
  const ta = document.createElement('textarea');
  ta.value = m.content;
  ta.rows = Math.min(12, Math.max(2, m.content.split('\n').length));
  ta.style.cssText =
    'width:100%;background:var(--bg-2);border:1px solid var(--border-2);border-radius:10px;padding:8px 10px;outline:none;';
  const actions = $('.msg-actions', row);
  content.replaceChildren(ta);
  actions.innerHTML =
    `<button class="btn primary" data-act="save-edit">Save & resend</button>` +
    `<button class="btn ghost" data-act="cancel-edit">Cancel</button>`;
  ta.focus();
  ta.setSelectionRange(ta.value.length, ta.value.length);
}

/* ── bindings ────────────────────────────────────────────── */
export function bindComposer() {
  const input = $('#input');
  const autosize = () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, window.innerHeight * 0.34) + 'px';
  };
  input.addEventListener('input', autosize);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendUser(input.value).then((sent) => { if (sent) { input.value = ''; autosize(); } });
    }
  });
  $('#btn-send').addEventListener('click', () => {
    sendUser(input.value).then((sent) => { if (sent) { input.value = ''; autosize(); } });
  });
  $('#btn-stop').addEventListener('click', stop);

  /* 1.7.0 mainstream focus behaviour (ChatGPT/Grok style):
     - clicking plain (non-interactive) text blurs the composer, so no caret
       keeps blinking somewhere while you read/select message text;
     - pressing any printable key on the chat page jumps focus back into the
       composer, so keyboard flow never breaks. */
  document.addEventListener('mousedown', (e) => {
    if (document.body.dataset.page !== 'chat') return;
    const t = e.target;
    if (t.closest('.composer, input, textarea, select, button, a, label, .model-menu, .profile-menu, .system-prompt-menu, .chat-debug-pop, .modal')) return;
    const ae = document.activeElement;
    if (ae && ae.id === 'input') ae.blur();
  });
  document.addEventListener('keydown', (e) => {
    if (document.body.dataset.page !== 'chat') return;
    if (e.key.length !== 1 || e.ctrlKey || e.metaKey || e.altKey) return;
    const ae = document.activeElement;
    if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.tagName === 'SELECT' || ae.isContentEditable || ae.tagName === 'BUTTON')) return;
    for (const id of ['confirm-dialog', 'model-import-dialog', 'personalization-dialog']) {
      if (!document.getElementById(id)?.classList.contains('hidden')) return;
    }
    if (!$('#model-menu')?.classList.contains('hidden') || !$('#profile-menu')?.classList.contains('hidden') || !$('#system-prompt-menu')?.classList.contains('hidden')) return;
    input.focus();
  });
}

export function bindMessageActions() {
  const box = $('#messages');
  box.addEventListener('scroll', () => {
    setPinned(box.scrollTop + box.clientHeight >= box.scrollHeight - 90);
    updateJumpBtn();
  });
  const jump = $('#jump-latest');
  if (jump) jump.addEventListener('click', () => { setPinned(true); scrollBottom(true); });
  box.addEventListener('click', (e) => {
    const copyBtn = e.target.closest('.cb-copy, .tb-copy');
    if (copyBtn) {
      const tb = copyBtn.closest('.tableblock');
      if (tb) { const csv=tableToCSV(tb.querySelector('table')); navigator.clipboard?.writeText(csv).then(()=>toast('Table copied as CSV.','ok',1600)); return; }
      const pre=copyBtn.closest('.codeblock').querySelector('pre'); navigator.clipboard?.writeText(pre.textContent).then(()=>toast('Code copied.','ok',1600)); return;
    }
    const td = e.target.closest('.cb-download, .tb-download');
    if (td) {
      const msgRow=td.closest('.msg-row'); const msg=msgRow ? activeChat()?.messages[Number(msgRow.dataset.idx)] : null;
      const safe=(v)=>String(v||'').replace(/[^a-z0-9._-]+/gi,'-').replace(/^-+|-+$/g,'').slice(0,70);
      if(td.classList.contains('cb-download')) {
        const block=td.closest('.codeblock'); const pre=block.querySelector('pre'); const code=pre.textContent;
        const lang=(block.querySelector('.cb-head span')?.textContent||'txt').trim();
        const ext={javascript:'js',js:'js',typescript:'ts',ts:'ts',python:'py',py:'py',json:'json',html:'html',css:'css',bash:'sh',shell:'sh',sh:'sh',sql:'sql',java:'java','c++':'cpp',cpp:'cpp',go:'go',rust:'rs',markdown:'md',md:'md',yaml:'yml',yml:'yml',typescriptreact:'tsx',tsx:'tsx',jsx:'jsx'}[lang.toLowerCase()]||'txt';
        const n=block.dataset.downloadIndex||'1'; const stem=safe(lang.toLowerCase()==='code'?'code':lang)||'code';
        downloadText(code,`archx-code-${n}-${stem}.${ext}`,'text/plain;charset=utf-8'); toast('Code downloaded.','ok',1400); return;
      }
      const block=td.closest('.tableblock'); const table=block.querySelector('table'), fmt=td.dataset.format||'csv'; let data,mime,ext;
      if(fmt==='json'){data=tableToJSON(table);mime='application/json';ext='json';} else if(fmt==='html'){data=tableToHTML(table);mime='text/html';ext='html';} else if(fmt==='md'){data=tableToMarkdown(table);mime='text/markdown';ext='md';} else if(fmt==='tsv'){data=tableToTSV(table);mime='text/tab-separated-values';ext='tsv';} else {data=tableToCSV(table);mime='text/csv';ext='csv';}
      const n=block.dataset.downloadIndex||'1'; downloadText(data,`archx-table-${n}.${ext}`,mime+';charset=utf-8'); toast(`Table downloaded as ${ext.toUpperCase()}.`,'ok',1400); return;
    }
    const act = e.target.closest('[data-act]');
    if (!act) return;
    const row = act.closest('.msg-row');
    const idx = Number(row.dataset.idx);
    const chat = activeChat();
    if (!chat) return;
    const m = chat.messages[idx];
    const action = act.dataset.act;
    if (action === 'copy') {
      const payload = m.reasoning ? `Reasoning:\n${m.reasoning}\n\n${m.content}` : m.content;
      if (navigator.clipboard) navigator.clipboard.writeText(payload).then(() => toast('Message copied.', 'ok', 1600));
    } else if (action === 'regen') {
      regenerate(idx);
    } else if (action === 'edit') {
      editUser(idx, row);
    } else if (action === 'cancel-edit') {
      renderMessages();
    } else if (action === 'save-edit') {
      const ta = $('textarea', row);
      const val = (ta.value || '').trim();
      if (!val) return;
      archiveBranch(chat, idx, 'edit');
      chat.messages.length = idx;
      chat.messages.push({ role: 'user', content: val, ts: Date.now() });
      touchChat(chat);
      renderMessages();
      complete(chat);
    }
  });
}

export { visibleModelsFor, setActive };
