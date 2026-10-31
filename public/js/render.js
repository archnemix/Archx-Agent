/* Archx Agent — UI renderer v4: profile viewer empty state, black/white accent */

import { $, $$, esc, ICON } from './dom.js';
import { paintBlocks } from './blocks.js';
import {
  state, visibleModels, visibleModelsFor, activeProvider, providerById, activeProfile,
  profileItem, activeChat, defaultSystemPrompt, enabledPromptsFor, freeCount, sortedProfileItems,
  providerModelGloballyEnabled, studioModelsFor, modelCaps,
} from './state.js';
import { normalizeTheme } from './theme.mjs';
import { capsFor, CAP_LABEL } from './capabilities.mjs';

/* 1.8.0: multi-select chats (issue 3) */
export const selectedChats = new Set();
export const PIN_ICON = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 17v5M9 3h6l1 7 3 2H5l3-2Z"/></svg>';

let pinned = true;
let profileAvailableProviderId = null;
/* 1.7.0: the profile OPEN IN THE EDITOR is separate from the profile ACTIVE
   FOR ROUTING. Opening/editing never changes what chats use; routing is
   changed only from the chat topbar menu or the (sr-only) active select. */
let openProfileId = null;
export function setOpenProfile(id) { openProfileId = id || null; }
export function editingProfile() { return state.profiles.find((p) => p.id === openProfileId) || null; }
let selectedModelProviderId = null;
const selectedModelIds = new Set();
export function toggleModelSelection(providerId, modelId, checked) {
  if (selectedModelProviderId !== providerId) { selectedModelProviderId = providerId; selectedModelIds.clear(); }
  if (checked) selectedModelIds.add(modelId); else selectedModelIds.delete(modelId);
}
export function selectedModelsFor(providerId) { return selectedModelProviderId === providerId ? [...selectedModelIds] : []; }
export function clearModelSelection() { selectedModelProviderId = null; selectedModelIds.clear(); }
export const isPinned = () => pinned;
export function setPinned(v) { pinned = v; }
export function setProfileAvailableProvider(id) {
  profileAvailableProviderId = id || null;
}

export function scrollBottom(force) {
  const box = $('#messages');
  if (!force && !pinned) return;
  box.scrollTop = box.scrollHeight;
  updateJumpBtn();
}

/* Layout metrics that floating elements need: the active page header height
   (toast anchor) and the composer height (jump-pill anchor). Both vary —
   the topbar wraps on mobile, the composer grows with the textarea and the
   storage note — so measure instead of hard-coding. */
export function updateLayoutVars() {
  const p = document.body.dataset.page || 'chat';
  const header = $(`#page-${p} .topbar`) || $(`#page-${p} .page-head`);
  if (header) document.documentElement.style.setProperty('--topbar-h', header.offsetHeight + 'px');
  const composer = $('.composer-wrap');
  if (composer) document.documentElement.style.setProperty('--composer-h', composer.offsetHeight + 'px');
}

/* "Jump to latest" pill — appears only while unpinned and away from the
   bottom, the way mainstream chat UIs do it. Pure affordance; scroll
   behaviour itself is unchanged. */
export function updateJumpBtn() {
  updateLayoutVars();
  const btn = $('#jump-latest');
  const box = $('#messages');
  if (!btn || !box) return;
  const away = box.scrollHeight - box.clientHeight - box.scrollTop > 240;
  btn.classList.toggle('hidden', !away);
}

export function applyTheme() {
  const theme = normalizeTheme(state.settings.theme);
  state.settings.theme = theme;
  document.documentElement.dataset.theme = theme;
  document.querySelectorAll('[data-theme-choice]').forEach((button) => {
    button.classList.toggle('active', button.dataset.themeChoice === theme);
    button.setAttribute('aria-pressed', String(button.dataset.themeChoice === theme));
  });
}

export function setConn(name) {
  const el = $('#conn-state');
  el.classList.remove('busy', 'err');
  if (name) el.classList.add(name);
}

export function setStreamingUI(on) {
  $('#btn-stop').classList.toggle('hidden', !on);
  $('#btn-send').disabled = on;
  setConn(on ? 'busy' : '');
}

export function metaText(m) {
  const bits = [];
  if (m.meta?.provider) bits.push(m.meta.provider);
  if (m.meta?.model) bits.push(m.meta.model);
  if (m.meta?.profile) bits.push(`profile: ${m.meta.profile}`);
  if (m.meta?.fallbackUsed || m.meta?.fallbackIndex > 0) bits.push('Fallback used');
  if (m.meta?.ms != null) bits.push((m.meta.ms / 1000).toFixed(1) + 's');
  if (m.meta?.tps) bits.push(m.meta.tps + ' tok/s');
  if (m.meta?.stopped) bits.push('stopped');
  if (m.meta?.incomplete) bits.push('incomplete');
  return bits.join(' · ');
}

/* ── sidebar ────────────────────────────────────────────── */
export function renderSidebar() {
  const list = $('#chat-list');
  list.innerHTML = '';
  $('#chat-count').textContent = state.chats.length ? `(${state.chats.length})` : '';
  const tempBtn = $('#temp-mode');
  if (tempBtn) { tempBtn.classList.toggle('on', state.tempMode); tempBtn.setAttribute('aria-pressed', String(state.tempMode)); }
  const selBtn = $('#select-mode');
  if (selBtn) { selBtn.classList.toggle('on', state.selectMode); selBtn.setAttribute('aria-pressed', String(state.selectMode)); }
  $('#select-bar')?.classList.toggle('hidden', !state.selectMode);
  const delBtn = $('#delete-selected-chats');
  if (delBtn) { delBtn.disabled = !selectedChats.size; delBtn.textContent = `Delete (${selectedChats.size})`; }
  // 1.8.0: pinned chats float to the top, recency order kept inside each group
  const ordered = state.chats.map((c, i) => [c, i]).sort((a, b) => ((b[0].pinned ? 1 : 0) - (a[0].pinned ? 1 : 0)) || (a[1] - b[1])).map((x) => x[0]);
  ordered.forEach((c) => {
    const item = document.createElement('div');
    item.className = 'chat-item' + (c.id === state.activeId ? ' active' : '') + (c.pinned ? ' pinned' : '') + (c.ephemeral ? ' ephemeral' : '');
    item.dataset.id = c.id;
    const sel = state.selectMode ? `<input type="checkbox" class="chat-sel" data-chat-sel="${esc(c.id)}" ${selectedChats.has(c.id) ? 'checked' : ''} aria-label="Select chat" />` : '';
    item.innerHTML = `${sel}<span class="title">${c.ephemeral ? '<span class="mini-tag">temp</span> ' : ''}${esc(c.title)}</span><span class="chat-item-actions"><button class="pin${c.pinned ? ' on' : ''}" type="button" title="${c.pinned ? 'Unpin chat' : 'Pin chat'}" data-chat-pin="${esc(c.id)}" aria-label="${c.pinned ? 'Unpin' : 'Pin'}">${PIN_ICON}</button><button class="del" title="Delete chat">${ICON.trash}</button></span>`;
    list.appendChild(item);
  });
  renderStorageNotes();
}

export function renderStorageNotes() {
  const mem = state.storage && state.storage.memoryOnly;
  $('#privacy-text').textContent = mem ? 'memory-only · nothing persisted' : 'keys encrypted · stored on this machine';
  $('#composer-note').textContent = mem
    ? 'Running memory-only: chats, keys and logs disappear when the server stops.'
    : `Data area: ${state.storage ? state.storage.dir : '…'} — SQLite data, encrypted keys & request logs`;
  const p = activeProvider();
  $('#endpoint-badge').textContent = p
    ? `${p.name} · ${p.host}${p.hasKey ? '' : ' · no key'}`
    : state.providers.length ? 'no active provider' : 'no provider configured';
  $('#endpoint-badge').classList.toggle('ok', !!p);
}

/* ── messages ────────────────────────────────────────────── */
/* ── 1.9.0: modern tool cards (searched the web / read page) ─────────── */
function toolCardHtml(t) {
  if (t.kind === 'web-search') {
    const head = t.error
      ? `<span class="tool-title">Web search failed</span><span class="tool-sub">${esc(t.error)}</span>`
      : `<span class="tool-title">Searched the web</span><span class="tool-sub">“${esc(t.query || '')}” · ${esc(t.engine || '…')} · ${t.ms || 0} ms</span>`;
    const sources = Array.isArray(t.results) && t.results.length
      ? `<details class="tool-sources"><summary>${t.results.length} sources</summary><ol>${t.results.map((r, i) => `<li><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title || r.url)}</a>${r.snippet ? `<p>${esc(r.snippet)}</p>` : ''}</li>`).join('')}</ol></details>`
      : '';
    return `<div class="tool-card${t.error ? ' err' : ''}"><span class="tool-ico">${t.error ? '⚠' : '⌕'}</span><div class="tool-copy">${head}${sources}</div></div>`;
  }
  if (t.kind === 'web-read') {
    const head = t.error
      ? `<span class="tool-title">Could not read page</span><span class="tool-sub">${esc(t.url)} · ${esc(t.error)}</span>`
      : `<span class="tool-title">Read page</span><span class="tool-sub">${esc(t.title || t.url)} · ${t.chars || 0} chars</span>`;
    return `<div class="tool-card${t.error ? ' err' : ''}"><span class="tool-ico">📄</span><div class="tool-copy">${head}<a class="tool-link" href="${esc(t.url)}" target="_blank" rel="noopener">${esc(t.url)}</a></div></div>`;
  }
  return '';
}
export function paintTools(container, msg) {
  if (!container) return;
  const tools = Array.isArray(msg?.tools) ? msg.tools : [];
  container.innerHTML = tools.map(toolCardHtml).join('');
  container.classList.toggle('empty', !tools.length);
}
export function appendLiveTool(row, tool) {
  const box = row && row.querySelector('.msg-tools');
  if (box) {
    box.insertAdjacentHTML('beforeend', toolCardHtml(tool));
    /* the row was painted pending (no tools yet) with .empty → display:none;
       un-hide now that a live tool card arrived */
    box.classList.remove('empty');
  }
}

export function paintContent(el, msg) {
  // 1.7.0: incremental block painting. Completed code blocks / tables /
  // reasoning panels keep their DOM identity while tokens arrive, so their
  // scrollbars never blink, drags survive, and the active block follows its
  // newest line until the user scrolls up inside it.
  paintBlocks(el, msg);
  let failure = el.querySelector('.msg-failure');
  if (msg.errorMessage) {
    if (!failure) {
      failure = document.createElement('div');
      failure.className = 'msg-failure';
      failure.setAttribute('role', 'alert');
      el.append(failure);
    }
    failure.textContent = msg.errorMessage;
  } else if (failure) failure.remove();
}

function msgRow(m, i) {
  const row = document.createElement('div');
  row.className = 'msg-row';
  row.dataset.idx = String(i);
  const isUser = m.role === 'user';
  row.innerHTML =
    `<div class="msg ${isUser ? 'user' : 'assistant'}${m.error ? ' error' : ''}">` +
    `<div class="avatar">${isUser ? 'YOU' : 'AX'}</div>` +
    `<div class="msg-body">` +
    `<div class="msg-head"><span class="msg-role">${isUser ? 'You' : 'Assistant'}</span><span class="msg-meta">${esc(metaText(m))}</span></div>` +
    `<div class="msg-tools"></div>` +
    `<div class="msg-content"></div>` +
    `<div class="msg-actions"><button class="icon-btn" data-act="copy" title="Copy message">${ICON.copy}</button>` +
    (isUser ? `<button class="icon-btn" data-act="edit" title="Edit and resend">${ICON.edit}</button>` : `<button class="icon-btn" data-act="regen" title="Regenerate">${ICON.regen}</button>`) +
    `</div></div></div>`;
  const content = $('.msg-content', row);
  if (isUser) content.textContent = m.content;
  else { paintTools($('.msg-tools', row), m); paintContent(content, m); }
  return row;
}

/* Branch indicator + menu contents (1.7.2). */
export function renderBranchUI() {
  const chat = activeChat();
  const branches = (chat && Array.isArray(chat.branches)) ? chat.branches : [];
  const btn = $('#branch-btn');
  const menu = $('#branch-menu');
  if (btn) {
    btn.classList.toggle('hidden', !branches.length);
    const count = $('#branch-count');
    if (count) count.textContent = String(branches.length);
  }
  if (!menu) return;
  menu.innerHTML = '';
  if (!branches.length) { menu.classList.add('hidden'); return; }
  const head = document.createElement('div');
  head.className = 'branch-menu-head';
  head.innerHTML = '<b>Alternate continuations</b><span class="hint">Opening one archives the current tail — nothing is lost.</span>';
  menu.appendChild(head);
  branches.slice().reverse().forEach((b) => {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'branch-row';
    row.dataset.branchOpen = b.id;
    const when = new Date(b.ts || Date.now()).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    row.innerHTML = `<span class="branch-origin ${String(b.origin || '').replace(/[^a-z-]/g, '')}">${esc(b.origin || 'branch')}</span><span class="branch-copy"><b>${esc(b.title || 'continuation')}</b><small>${(b.messages || []).length} messages · ${when}</small></span><span class="branch-open-label">Open ›</span>`;
    menu.appendChild(row);
  });
}

export function renderMessages() {
  const picker = $('#chat-mode');
  if (picker) {
    const chat = activeChat();
    const mode = chat?.modeId || 'simple-chat';
    const modes = [...state.modes];
    for (const pending of [{ id: 'agent', name: 'Agent — not available yet' }, { id: 'research', name: 'Research — not available yet' }]) {
      if (!modes.some(m => m.id === pending.id)) modes.push({ ...pending, unavailable: true });
    }
    picker.innerHTML = modes.map(m => `<option value="${esc(m.id)}" ${mode === m.id ? 'selected' : ''} ${m.unavailable ? 'disabled' : ''}>${esc(m.name)}</option>`).join('');
    picker.disabled = mode !== 'simple-chat';
    picker.title = mode === 'simple-chat' ? 'A conversion to a specialised mode cannot be reversed.' : 'This conversation is locked to its mode. Start a new chat for another mode.';
  }

  const box = $('#messages');
  $$('.msg-row', box).forEach((n) => n.remove());
  const chat = activeChat();
  const hasMessages = !!(chat && chat.messages.length);
  const hasProviders = state.providers.length > 0;
  $('#empty').classList.toggle('hidden', hasMessages || !hasProviders);
  $('#no-provider').classList.toggle('hidden', hasMessages || hasProviders);
  if (hasMessages) {
    const frag = document.createDocumentFragment();
    chat.messages.forEach((m, i) => frag.appendChild(msgRow(m, i)));
    box.appendChild(frag);
  } else if (hasProviders) {
    $('#empty-model').textContent = state.active.model || 'your model';
  }
  renderBranchUI();
  scrollBottom(true);
}

/* ── top bar / model menus ───────────────────────────────── */
export function renderModelUI() {
  const p = activeProvider();
  const profile = state.settings.advancedProfiles ? activeProfile() : null;
  $('#model-label').textContent = p
    ? state.active.model ? `${p.name} / ${state.active.model}` : `${p.name} / pick a model`
    : state.providers.length ? 'no active provider' : 'no provider';
  // 1.8.0 (issue 2): the chat picker only offers chat-capable models
  const vis = visibleModels().filter((m) => modelCaps(p?.id, m.id).chat);
  $('#conn-state').textContent = p
    ? `${p.host}${vis.length ? ' · ' + vis.length + ' models' : ''}${p.hasKey ? '' : ' · no key'}`
    : 'not configured';
  $('#conn-state').classList.toggle('ok', !!p);
  $('#comp-meta').textContent = state.active.model
    ? `${state.active.model} · temp ${Number(state.settings.temperature).toFixed(1)}${state.settings.stream ? ' · streaming' : ''}${profile ? ` · ${profile.name}` : ''}`
    : '';
  $('#empty-model').textContent = state.active.model || 'your model';

  $('.brand > span').textContent = state.settings.agentName || 'Archx Agent';
  const wrap = $('#profile-wrap');
  // The picker was unconditionally hidden here, so profiles could never be
  // selected or cleared from Chat. It belongs to the advanced-profiles mode.
  wrap.classList.toggle('hidden', !state.settings.advancedProfiles);
  $('#profile-label').textContent = profile ? profile.name : 'No profile';
  $('#profile-btn')?.classList.toggle('none', !profile);
  if (!profile && $('#profile-menu')) $('#profile-menu').classList.add('hidden');
  renderProfileMenu();
  renderSystemPromptUI();
}

export function renderModelMenu(selId) {
  // 1.6.6: while a profile routes requests, direct model picking is disabled —
  // the menu says so instead of silently detaching the chain on click.
  const locked = !!(state.settings.advancedProfiles && activeProfile());
  const lock = $('#mm-lock');
  if (lock) {
    lock.classList.toggle('hidden', !locked);
    if (locked) lock.textContent = `Profile “${activeProfile().name}” is routing by priority. Choose “No profile” in the profile menu to pick models directly.`;
  }
  const mList = $('#model-list');
  if (mList) mList.classList.toggle('locked', locked);
  const provs = $('#mm-provs');
  provs.innerHTML = '';
  if (!state.providers.length) provs.innerHTML = '<div class="empty-line">no providers yet — add one in Settings</div>';
  state.providers.forEach((p) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'mm-prov' + (p.id === selId ? ' sel' : '');
    b.dataset.prov = p.id;
    const dot = p.keyError ? 'err' : p.hasKey ? '' : 'none';
    b.innerHTML = `<span class="pname"><span class="dot ${dot}"></span>${esc(p.name)}${p.freeOnly ? '<span class="freebadge">free only</span>' : ''}</span><span class="phost">${esc(p.host)}</span>`;
    provs.appendChild(b);
  });
  const p = providerById(selId);
  const warn = $('#mm-warn');
  const list = $('#model-list');
  list.innerHTML = '';
  if (!p) { warn.classList.add('hidden'); $('#model-count').textContent = ''; return; }
  const loaded = !!state.providerModels[p.id];
  const vis = visibleModelsFor(p);
  if (p.freeOnly && loaded && freeCount(p) === 0) {
    warn.textContent = `⚠ ${p.name} has no models tagged free. Turn “free only” off, or add your own ids in Settings → Models.`;
    warn.classList.remove('hidden');
  } else warn.classList.add('hidden');
  const q = ($('#model-search').value || '').toLowerCase();
  const shown = vis.filter((m) => (!q || m.id.toLowerCase().includes(q)) && modelCaps(p.id, m.id).chat);
  if (!loaded) list.innerHTML = '<div class="empty-line">loading model list…</div>';
  else if (!shown.length) list.innerHTML = `<div class="empty-line">no model matches “${esc(q)}”</div>`;
  shown.forEach((m) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'model-opt' + (p.id === state.active.providerId && m.id === state.active.model ? ' sel' : '');
    b.dataset.model = m.id;
    b.innerHTML = `<span class="mid">${esc(m.id)}</span><span class="mown">${esc(m.custom ? 'custom' : m.owned_by || '')}${m.profile ? ' · <span class="mini-tag">in profile</span>' : ''}</span>`;
    list.appendChild(b);
  });
  $('#model-count').textContent = loaded ? `${shown.length}/${vis.length} visible · ${freeCount(p)} free` : 'fetching…';
}

export function renderSystemPromptUI() {
  const menu = $('#system-prompt-menu');
  const list = $('#system-prompt-list');
  if (!menu || !list) return;
  const chat = activeChat();
  // With no open chat, new chats inherit the default prompt — show that instead
  // of "No system prompt", which is only true once the user explicitly picks it.
  const stack = chat ? enabledPromptsFor(chat) : (defaultSystemPrompt() ? [defaultSystemPrompt()] : []);
  const mode = state.settings.systemPromptMode === 'replace' ? 'replace' : 'stack';
  $('#system-prompt-label').textContent = !stack.length
    ? 'No system prompt'
    : stack[0].name + (stack.length > 1 ? ` +${stack.length - 1}` : '');
  list.innerHTML = '';
  // 1.6.7: pure checkboxes — no separate "No system prompt" entry; unticking
  // everything is exactly that. The whole row is the toggle's label.
  (state.settings.systemPrompts || []).forEach((prompt) => {
    const enabled = stack.some((p) => p.id === prompt.id);
    const row = document.createElement('label');
    row.className = 'profile-option sp-menu-row' + (enabled ? ' sel' : '');
    row.title = enabled ? 'Sent with this chat — click to stop sending' : 'Not sent — click to send';
    row.innerHTML =
      `<span class="profile-option-main"><b>${esc(prompt.name)}</b>` +
      `<span>${esc((prompt.content || '').trim().slice(0, 90) || 'Empty prompt')}</span></span>` +
      (prompt.id === state.settings.defaultSystemPromptId ? '<span class="profile-option-priority">default</span>' : '') +
      `<input type="checkbox" class="sp-switch" role="switch" aria-label="${enabled ? 'Stop sending' : 'Send'} prompt ${esc(prompt.name)} in this chat" data-sp-toggle="${esc(prompt.id)}" ${enabled ? 'checked' : ''} ${chat ? '' : 'disabled'} />`;
    list.appendChild(row);
  });
  const hint = $('#system-prompt-stack-hint');
  if (hint) {
    hint.textContent = !chat
      ? 'New chats start with the default prompt checked.'
      : mode === 'replace'
        ? `Replace mode: ${stack.length} checked prompt${stack.length === 1 ? '' : 's'} merged into one system message.`
        : `Stack mode: ${stack.length} checked prompt${stack.length === 1 ? '' : 's'} sent — first as system, later ones tagged “update:”. Untick all to send none.`;
  }
  const preview = $('#system-prompt-effective-preview');
  if (preview) {
    const settings = state.settings || {};
    const values = { username: String(settings.username || ''), age: String(settings.age || ''), preferredName: String(settings.preferredName || settings.username || ''), agentName: String(settings.agentName || 'Archx Agent') };
    const expand = (v) => String(v || '').replace(/\{\s*(username|age|preferredName|agentName)\s*\}/gi, (_, key) => values[key.charAt(0).toLowerCase() + key.slice(1)] || '');
    const personalization = [`User preferred name: ${values.preferredName}`, `User age: ${values.age}`, `Agent name: ${values.agentName}`].filter((x) => x.split(': ')[1]);
    if (!stack.length) preview.textContent = '(No system message will be sent. User and agent personalization is therefore not injected either.)';
    else if (mode === 'replace') {
      const merged = stack.map((p) => expand(p.content).trim()).filter(Boolean).join('\n\n');
      preview.textContent = merged + (personalization.length ? `\n\n[Archx personalization context]\n${personalization.map((x) => '- ' + x).join('\n')}\n[/Archx personalization context]` : '');
    } else {
      const messages = stack.map((p, i) => `${i ? 'update: ' : ''}${expand(p.content).trim()}`).map((content, i) => `[SYSTEM ${i + 1}]\n${content}`);
      if (personalization.length) messages[0] += `\n\n[Archx personalization context]\n${personalization.map((x) => '- ' + x).join('\n')}\n[/Archx personalization context]`;
      preview.textContent = messages.join('\n\n');
    }
  }
}

/* 1.6.7 editor model: a plain list of prompts on the left, one editor below.
   Click a prompt to open it; change name/text; Save. "New prompt" drafts an
   empty one and focuses the name field. The default prompt can be edited but
   never deleted — it ships with the app and starts checked in every chat. */
let spEditingId = null;
export const getSpEditing = () => spEditingId;
export function setSpEditing(id) { spEditingId = id; }

export function renderSystemPromptSettings() {
  const list = $('#sp-list'), name = $('#set-system-prompt-name'), ta = $('#set-system'), del = $('#set-system-prompt-delete');
  if (!list || !name || !ta) return;
  const prompts = state.settings.systemPrompts || [];
  if (!spEditingId || !prompts.some((p) => p.id === spEditingId)) {
    spEditingId = state.settings.defaultSystemPromptId || prompts[0]?.id || null;
  }
  const prompt = prompts.find((p) => p.id === spEditingId) || null;
  list.innerHTML = '';
  prompts.forEach((p) => {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'sp-row' + (p.id === spEditingId ? ' active' : '');
    row.dataset.spEdit = p.id;
    row.innerHTML =
      `<span class="sp-row-main"><b>${esc(p.name)}</b><span>${esc((p.content || '').trim().slice(0, 80) || 'Empty prompt')}</span></span>` +
      (p.id === state.settings.defaultSystemPromptId ? '<span class="profile-option-priority">default</span>' : '');
    list.appendChild(row);
  });
  name.value = prompt?.name || '';
  ta.value = prompt?.content || '';
  if (del) del.disabled = !prompt || prompt.id === state.settings.defaultSystemPromptId;
}

export function renderProfileMenu() {
  const list = $('#profile-list');
  if (!list) return;
  list.innerHTML = '';
  // 1.7.0: "No profile" is a first-class, clearly bordered option row — the
  // old ghost-text button read as a broken label and was easy to miss.
  const none = document.createElement('button');
  none.type = 'button';
  none.className = 'profile-option profile-option-none' + (state.activeProfileId ? '' : ' sel');
  none.dataset.profileId = '';
  none.innerHTML = '<span class="profile-option-main"><b>No profile</b><span>Pick models directly — no priority routing</span></span><span class="profile-option-priority">direct</span>';
  list.appendChild(none);
  if (!state.profiles.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-line';
    empty.textContent = 'No profiles yet. Create one in Settings → Profiles.';
    list.appendChild(empty);
    return;
  }
  state.profiles.forEach((profile) => {
    const items = sortedProfileItems(profile);
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'profile-option' + (profile.id === state.activeProfileId ? ' sel' : '');
    card.dataset.profileId = profile.id;
    const on = profile.id === state.activeProfileId;
    card.innerHTML = `<span class="profile-option-main"><b>${esc(profile.name)}</b><span>${items.length} model${items.length === 1 ? '' : 's'} · ${esc([...new Set(items.map((x) => providerById(x.providerId)?.name || 'missing'))].join(' · '))}</span></span><span class="profile-option-priority">P${items[0]?.priority || 1}</span><span class="switch${on ? ' on' : ''}" role="switch" tabindex="0" aria-checked="${on}" aria-label="${on ? 'Disable' : 'Enable'} profile ${esc(profile.name)}" data-profile-switch="${esc(profile.id)}"></span>`;
    list.appendChild(card);
  });
}

/* ── settings: providers ─────────────────────────────────── */
export function renderSettingsProviders() {
  const box = $('#prov-list');
  box.innerHTML = '';
  if (!state.providers.length) { box.innerHTML = '<div class="empty-line">No providers yet. Use <b>Add provider</b> above.</div>'; return; }
  state.providers.forEach((p) => {
    const card = document.createElement('article');
    card.className = 'provider-card';
    const keyTxt = p.keyError ? 'key undecryptable — re-enter' : p.hasKey ? `key ${p.keyMasked}` : 'no key';
    const active = p.id === state.active.providerId;
    card.innerHTML = `<div class="provider-card-main"><div class="provider-icon">${esc((p.name || 'P').slice(0, 1).toUpperCase())}</div><div class="provider-card-copy"><div class="provider-title"><b>${esc(p.name)}</b>${active ? '<span class="tag">active</span>' : ''}${p.defaultModel ? `<span class="tag">default ${esc(p.defaultModel)}</span>` : ''}</div><div class="provider-url">${esc(p.baseUrl)}</div><div class="provider-meta"><span class="status-dot ${p.keyError ? 'bad' : p.hasKey ? 'good' : 'none'}"></span>${esc(keyTxt)}<span>•</span><span>${p.freeOnly ? 'free only' : 'all models'}</span><span>•</span><span>adapter ${esc(p.adapter || 'openai-compatible')}</span></div></div><div class="provider-card-actions"><button class="btn" data-prov-act="test" data-id="${p.id}">Test</button><button class="btn" data-prov-act="edit" data-id="${p.id}">Edit</button><button class="btn danger" data-prov-act="del" data-id="${p.id}">Delete</button></div></div>`;
    box.appendChild(card);
  });
}

export function settingsModelProviderId() {
  const sel = $('#mdl-provider-sel');
  if (sel.value && providerById(sel.value)) return sel.value;
  return state.active.providerId || state.providers[0]?.id || null;
}

function profileHasItem(profile, providerId, model) {
  return !!profileItem(profile, providerId, model);
}

export function renderSettingsModels() {
  const sel = $('#mdl-provider-sel');
  const keep = sel.value;
  sel.innerHTML = '';
  state.providers.forEach((p) => { const o = document.createElement('option'); o.value = p.id; o.textContent = `${p.name} (${p.host})`; sel.appendChild(o); });
  const pid = keep && providerById(keep) ? keep : settingsModelProviderId();
  sel.value = pid || '';
  const p = providerById(pid);
  const tabs = $('#mdl-provider-tabs');
  if (tabs) {
    tabs.innerHTML = '';
    if (!state.providers.length) {
      tabs.innerHTML = '<div class="empty-line">Add a provider first.</div>';
    } else state.providers.forEach((provider) => {
      const live = state.providerModels[provider.id] || [];
      const configured = configuredModelRows(provider);
      const enabledCount = configured.filter((m) => providerModelGloballyEnabled(provider, m.id, live)).length;
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'provider-tab' + (provider.id === pid ? ' active' : '');
      b.dataset.providerId = provider.id;
      b.innerHTML = `<span class="provider-tab-mark">${esc((provider.name || 'P').slice(0, 1).toUpperCase())}</span><span class="provider-tab-copy"><b>${esc(provider.name)}</b><small>${esc(provider.host || '')}</small></span><span class="provider-tab-count">${enabledCount}</span>`;
      tabs.appendChild(b);
    });
  }

  const profile = editingProfile() || activeProfile();
  const profileSel = $('#mdl-profile-sel');
  if (profileSel) {
    profileSel.innerHTML = '<option value="">No active profile</option>';
    state.profiles.forEach((pr) => { const o = document.createElement('option'); o.value = pr.id; o.textContent = pr.name; profileSel.appendChild(o); });
    profileSel.value = state.activeProfileId || '';
  }
  const profileName = $('#mdl-profile-name');
  if (profileName && document.activeElement !== profileName) profileName.value = profile?.name || '';
  const delBtn = $('#mdl-profile-delete');
  const saveBtn = $('#mdl-profile-save');
  if (delBtn) delBtn.disabled = !profile;
  if (saveBtn) saveBtn.disabled = !profile;

  renderProviderModelWorkspace(p);
  renderProfileEditor(profile);
}

function isProviderModelEnabled(provider, model) {
  const hidden = new Set(provider.models.hidden || []);
  if (hidden.has(model.id)) return false;
  if (!provider.freeOnly) return true;
  return isFreeLocal(model) || (provider.freeOnlyManualEnabled || []).includes(model.id);
}

function providerModelIsEnabledById(provider, id, models) {
  const hidden = new Set(provider.models.hidden || []);
  if (hidden.has(id)) return false;
  if (!provider.freeOnly) return true;
  const m = (models || []).find((x) => x.id === id);
  return isFreeLocal(m || { id }) || (provider.freeOnlyManualEnabled || []).includes(id);
}

function makeModelRow({ id, enabled, free, action, secondary = '', test = true, providerId }) {
  const row = document.createElement('div');
  row.className = 'model-row';
  const selected = selectedModelProviderId === providerId && selectedModelIds.has(id);
  const caps = modelCaps(providerId, id);
  const capTags = Object.entries(caps).filter(([key, v]) => v && key !== 'chat').map(([key]) => `<span class="mini-tag cap">${esc(CAP_LABEL[key] || key)}</span>`).join('');
  row.innerHTML = `<div class="model-row-main"><input class="model-select-box" type="checkbox" data-model-select="1" data-id="${esc(id)}" ${selected ? 'checked' : ''} aria-label="Select ${esc(id)}" /><span class="model-row-dot ${enabled ? 'on' : ''}"></span><span class="model-row-name" title="${esc(id)}">${esc(id)}</span>${free ? '<span class="mini-tag free">free</span>' : ''}${capTags}${secondary ? `<span class="model-row-meta">${esc(secondary)}</span>` : ''}</div><div class="model-row-actions"><button class="btn tiny" data-model-probe="1" data-id="${esc(id)}" type="button" title="Edit test body & capability overrides">Probe</button>${test ? `<button class="btn tiny" data-mdltst="1" data-id="${esc(id)}" type="button">Test</button>` : ''}<button class="btn tiny ${enabled ? '' : 'primary'}" data-model-toggle="1" data-id="${esc(id)}" type="button">${esc(action)}</button><button class="btn tiny danger" data-model-delete="1" data-id="${esc(id)}" type="button">Delete</button></div>`;
  return row;
}

function configuredModelRows(p) {
  const raw = state.providerModels[p.id] || [];
  const catalog = Array.isArray(p.models.catalog) ? p.models.catalog : [];
  const custom = new Set(p.models.custom || []);
  const ids = [...catalog, ...custom].filter((id, i, arr) => arr.indexOf(id) === i);
  const byId = new Map(raw.map((m) => [m.id, m]));
  return ids.map((id) => ({ id, free: isFreeLocal(byId.get(id) || { id }), custom: custom.has(id), live: byId.get(id) || null }));
}

function renderProviderModelWorkspace(p) {
  const title = $('#mdl-provider-title'), summary = $('#mdl-summary');
  const enabledBox = $('#mdl-enabled'), disabledBox = $('#mdl-disabled');
  const enabledCountEl = $('#mdl-enabled-count'), disabledCountEl = $('#mdl-disabled-count');
  if (!p) {
    clearModelSelection();
    if (title) title.textContent = 'No provider selected';
    if (summary) summary.innerHTML = '<span class="empty-summary">Configure a provider to begin.</span>';
    [enabledBox, disabledBox].forEach((el) => { if (el) el.innerHTML = '<div class="empty-line">—</div>'; });
    [enabledCountEl, disabledCountEl].forEach((el) => { if (el) el.textContent = '0'; });
    $('#mdl-free-only').disabled = true;
    $('#mdl-free-only').checked = false;
    $('#mdl-free-warn').classList.add('hidden');
    $('#mdl-custom-add').disabled = true;
    $('#mdl-custom-input').disabled = true;
    const delSelected = $('#mdl-delete-selected');
    if (delSelected) { delSelected.disabled = true; delSelected.textContent = 'Delete selected'; }
    return;
  }
  if (title) title.textContent = p.name;
  $('#mdl-custom-add').disabled = false;
  $('#mdl-custom-input').disabled = false;
  const free = $('#mdl-free-only');
  free.disabled = false;
  free.checked = !!p.freeOnly;
  const loaded = !!state.providerModels[p.id];
  const warn = $('#mdl-free-warn');
  const raw = state.providerModels[p.id] || [];
  const rows = configuredModelRows(p);
  if (p.freeOnly && loaded && freeCount(p) === 0) { warn.textContent = 'No provider models are tagged free. Manually enabled models remain available.'; warn.classList.remove('hidden'); }
  else warn.classList.add('hidden');
  const q = ($('#mdl-search').value || '').toLowerCase();
  const filtered = rows.filter((m) => !q || m.id.toLowerCase().includes(q));
  const enabledRows = filtered.filter((m) => providerModelGloballyEnabled(p, m.id, raw));
  const disabledRows = filtered.filter((m) => !providerModelGloballyEnabled(p, m.id, raw));
  const allEnabledCount = rows.filter((m) => providerModelGloballyEnabled(p, m.id, raw)).length;
  const allDisabledCount = rows.length - allEnabledCount;
  if (summary) summary.innerHTML = `<span class="summary-value">${rows.length}</span><span class="summary-label">in list</span><span class="summary-divider">·</span><span class="summary-value">${allEnabledCount}</span><span class="summary-label">enabled</span><span class="summary-divider">/</span><span class="summary-value">${allDisabledCount}</span><span class="summary-label">disabled</span>`;
  if (enabledCountEl) enabledCountEl.textContent = String(enabledRows.length);
  if (disabledCountEl) disabledCountEl.textContent = String(disabledRows.length);

  enabledBox.innerHTML = '';
  if (!loaded && !rows.length) enabledBox.innerHTML = '<div class="empty-state compact"><b>No models configured</b><span>Use Fetch models to discover this provider. Newly fetched models only enter the list when you check them.</span></div>';
  else if (!enabledRows.length) enabledBox.innerHTML = '<div class="empty-state compact"><b>No enabled models</b><span>Enable a model from Disabled to make it available in Chat.</span></div>';
  enabledRows.forEach((m) => enabledBox.appendChild(makeModelRow({ id: m.id, providerId: p.id, enabled: true, free: m.free, secondary: m.custom ? 'custom' : '', action: 'Disable' })));

  disabledBox.innerHTML = '';
  if (!disabledRows.length) disabledBox.innerHTML = '<div class="empty-state compact"><b>Nothing disabled</b><span>Every model in this provider list is enabled.</span></div>';
  disabledRows.forEach((m) => disabledBox.appendChild(makeModelRow({ id: m.id, providerId: p.id, enabled: false, free: m.free, secondary: m.custom ? 'custom' : '', action: 'Enable' })));
  const delSelected = $('#mdl-delete-selected');
  if (delSelected) { const selected = p ? selectedModelsFor(p.id) : []; delSelected.disabled = !selected.length; delSelected.textContent = selected.length ? `Delete selected (${selected.length})` : 'Delete selected'; }
}

function renderProfileEditor(profile) {
  const providerSel = $('#mdl-profile-provider');
  providerSel.innerHTML = '';
  state.providers.forEach((p) => { const o = document.createElement('option'); o.value = p.id; o.textContent = p.name; providerSel.appendChild(o); });
  const list = $('#mdl-profile-list');
  list.innerHTML = '';
  $('#mdl-profile-count').textContent = String(state.profiles.length);
  // 1.7.0: zero profiles → single-column calm state instead of an empty viewer box
  document.querySelector('.profile-workspace')?.classList.toggle('no-profiles', !state.profiles.length);
  if (!state.profiles.length) list.innerHTML = '<div class="empty-state compact"><b>No profiles yet</b><span>Create a profile to build a reusable fallback chain.</span></div>';
  state.profiles.forEach((pr) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'profile-list-item' + (pr.id === (openProfileId || state.activeProfileId) ? ' active' : '');
    btn.dataset.profileId = pr.id;
    const providers = [...new Set(pr.items.map((x) => providerById(x.providerId)?.name || 'Missing provider'))];
    const paused = pr.items.filter((x) => x.enabled === false).length;
    btn.innerHTML = `<span class="profile-list-icon">${esc((pr.name || 'P').slice(0, 1).toUpperCase())}</span><span class="profile-list-copy"><b>${esc(pr.name)}</b><small>${pr.items.length} model${pr.items.length === 1 ? '' : 's'} · ${paused ? `${paused} paused · ` : ''}${esc(providers.join(' · ') || 'empty')}${pr.id === state.activeProfileId ? ' · routing' : ''}</small></span><span class="profile-list-chevron">›</span>`;
    list.appendChild(btn);
  });

  const viewer = $('#mdl-profile-viewer');
  const title = $('#mdl-profile-title');
  const subtitle = $('#mdl-profile-subtitle');
  const itemsBox = $('#mdl-profile-items');
  const available = $('#mdl-profile-available');
  const enabledCount = $('#mdl-profile-enabled-count');
  const tabs = $('#mdl-profile-provider-tabs');

  if (!profile) {
    title.textContent = 'No profile selected';
    subtitle.textContent = 'Create a profile above, or click one on the left to manage its fallback chain.';
    enabledCount.textContent = '0';
    itemsBox.innerHTML = '';
    available.innerHTML = '';
    if (tabs) tabs.innerHTML = '';
    viewer.classList.add('empty');
    return;
  }
  viewer.classList.remove('empty');

  title.textContent = profile.name;
  const paused = profile.items.filter((x) => x.enabled === false).length;
  const parked = profile.items.filter((x) => x.parked === true).length;
  subtitle.textContent = `${profile.description ? profile.description + ' · ' : ''}${profile.items.length} model${profile.items.length === 1 ? '' : 's'} · ${paused ? `${paused} paused · ` : ''}${parked ? `${parked} awaiting provider · ` : ''}global model disable always applies`;
  enabledCount.textContent = String(profile.items.filter((x) => x.enabled !== false).length);
  const items = sortedProfileItems(profile);
  itemsBox.innerHTML = '';
  if (!items.length) itemsBox.innerHTML = '<div class="empty-state compact"><b>Empty profile</b><span>Add a model from Available to add it to this chain.</span></div>';
  items.forEach((item, index) => {
    const pr = providerById(item.providerId);
    const globalEnabled = providerModelGloballyEnabled(pr, item.model, state.providerModels[item.providerId] || []);
    const row = document.createElement('div');
    row.className = `profile-item ${item.enabled === false ? 'profile-paused' : ''}`;
    row.innerHTML = `<span class="profile-order">${index + 1}</span><span class="profile-item-copy"><b>${esc(pr?.name || 'Missing provider')}</b><span>${esc(item.model)}</span><span class="profile-item-status">${item.parked ? `provider removed (${esc(item.parkedProviderName || '?')}) — paused until re-attached` : !globalEnabled ? 'globally disabled / not configured' : item.enabled === false ? 'paused in this profile' : 'active in this profile'}</span></span><label class="profile-prio"><span>Priority</span><input type="number" min="1" step="1" value="${Number(item.priority) || 1}" data-profile-priority-provider="${esc(item.providerId)}" data-profile-priority-model="${esc(item.model)}" /></label><button class="btn tiny ${item.enabled === false ? 'primary' : ''}" data-profile-toggle-provider="${esc(item.providerId)}" data-profile-toggle-model="${esc(item.model)}" type="button">${item.enabled === false ? 'Resume' : 'Pause'}</button><button class="icon-btn danger" title="Remove from profile" data-profile-remove-provider="${esc(item.providerId)}" data-profile-remove-model="${esc(item.model)}">${ICON.trash}</button>`;
    itemsBox.appendChild(row);
  });

  const profileProviderIds = [...new Set(profile.items.map((x) => x.providerId))];
  if (!profileAvailableProviderId || !state.providers.some((p) => p.id === profileAvailableProviderId)) profileAvailableProviderId = profileProviderIds[0] || state.providers[0]?.id || null;
  if (tabs) {
    tabs.innerHTML = '';
    state.providers.forEach((pr) => {
      const models = configuredModelRows(pr).filter((m) => providerModelGloballyEnabled(pr, m.id, state.providerModels[pr.id] || []));
      const included = new Set(profile.items.filter((x) => x.providerId === pr.id).map((x) => x.model));
      const count = models.filter((m) => !included.has(m.id)).length;
      const tab = document.createElement('button');
      tab.type = 'button';
      tab.className = 'provider-tab' + (pr.id === profileAvailableProviderId ? ' active' : '');
      tab.dataset.profileProviderId = pr.id;
      tab.innerHTML = `<span class="provider-tab-mark">${esc((pr.name || 'P').slice(0, 1).toUpperCase())}</span><span class="provider-tab-copy"><b>${esc(pr.name)}</b><small>${esc(pr.host || '')}</small></span><span class="provider-tab-count">${count}</span>`;
      tabs.appendChild(tab);
    });
  }

  const included = new Set(profile.items.map((x) => `${x.providerId}\u0000${x.model}`));
  available.innerHTML = '';
  const currentProvider = providerById(profileAvailableProviderId);
  const raw = currentProvider ? state.providerModels[currentProvider.id] || [] : [];
  const models = currentProvider ? configuredModelRows(currentProvider).filter((m) => providerModelGloballyEnabled(currentProvider, m.id, raw) && !included.has(`${currentProvider.id}\u0000${m.id}`)) : [];
  if (currentProvider && !state.providerModels[currentProvider.id]) {
    available.innerHTML = '<div class="empty-state compact"><b>Provider models not fetched yet</b><span>Use Fetch models above to discover and add this provider’s models.</span></div>';
  } else if (!models.length) {
    available.innerHTML = '<div class="empty-state compact"><b>No models available to add</b><span>Enable or add models in Model Control first, then return here.</span></div>';
  } else {
    const group = document.createElement('div');
    group.className = 'profile-available-group';
    group.innerHTML = `<div class="profile-available-head"><span><b>${esc(currentProvider.name)}</b><small>${esc(currentProvider.host || '')}</small></span><span class="count-pill">${models.length}</span></div><div class="profile-available-list"></div>`;
    const box = group.querySelector('.profile-available-list');
    models.forEach((m) => {
      const row = document.createElement('div');
      row.className = 'profile-available-row';
      row.innerHTML = `<div class="model-row-main"><span class="model-row-dot on"></span><span class="model-row-name" title="${esc(m.id)}">${esc(m.id)}</span>${m.free ? '<span class="mini-tag free">free</span>' : m.custom ? '<span class="model-row-meta">custom</span>' : ''}</div><button class="btn tiny primary" data-profile-add-provider="${esc(currentProvider.id)}" data-profile-add-model="${esc(m.id)}" type="button">Add</button>`;
      box.appendChild(row);
    });
    available.appendChild(group);
  }
}

function isFreeLocal(m) {
  if (/(^|[:/_-])free$/i.test(m.id || '')) return true;
  const pr = m.pricing;
  return !!(pr && Number(pr.prompt) === 0 && Number(pr.completion) === 0);
}

/* ── settings: storage + fill ────────────────────────────── */
export function renderSettingsStorage() {
  const s = state.storage;
  $('#sto-current').textContent = s && s.memoryOnly ? 'memory-only (nothing persisted)' : s ? s.dir : '…';
  $('#sto-logs').textContent = s && s.memoryOnly ? 'disabled in memory-only mode' : s ? s.database : '…';
  $('#sto-manifest').textContent = s && s.manifest ? `${s.manifestPath}  ·  FIXED (never moves)  ·  engine: ${s.manifest.storage.engine}  ·  app: ${s.manifest.app.installPath}` : '…';
}

export function fillSettings() {
  $('#set-username').value = state.settings.username || '';
  $('#set-age').value = state.settings.age || '';
  $('#set-preferred-name').value = state.settings.preferredName || '';
  $('#set-agent-name').value = state.settings.agentName || 'Archx Agent';
  $('#set-system').value = state.settings.system || '';
  $('#set-temp').value = String(state.settings.temperature);
  $('#temp-val').textContent = Number(state.settings.temperature).toFixed(1);
  $('#set-max').value = state.settings.maxTokens || '';
  $('#set-stream').checked = !!state.settings.stream;
  $('#set-reasoning').checked = state.settings.reasoning !== false;
  $('#set-advanced-profiles').checked = state.settings.advancedProfiles === true;
  $('#set-logs-simple').checked = (state.settings.logsMode || 'simple') === 'simple';
  $('#set-logs-detailed').checked = state.settings.logsMode === 'detailed-encrypted';
  const spm = state.settings.systemPromptMode === 'replace' ? 'replace' : 'stack';
  if ($('#sp-mode-stack')) $('#sp-mode-stack').checked = spm === 'stack';
  if ($('#sp-mode-replace')) $('#sp-mode-replace').checked = spm === 'replace';
  renderSystemPromptSettings();
  renderSystemPromptUI();
  renderSettingsProviders();
  renderSettingsModels();
  renderSettingsStorage();
}

/* ── 1.8.0 helpers: byte formatting, studio selects, memory page ── */
export function fmtBytes(n) {
  const v = Number(n) || 0;
  if (v < 1024) return `${Math.round(v)} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let x = v;
  let i = -1;
  while (x >= 1024 && i < units.length - 1) { x /= 1024; i += 1; }
  const r = x >= 100 ? Math.round(x) : Math.round(x * 10) / 10;
  return `${r} ${units[i]}`;
}

export function fillStudioSelect(sel, kind, cached) {
  if (!sel) return;
  const items = studioModelsFor(kind);
  const prev = cached || sel.value || '';
  sel.innerHTML = items.length
    ? items.map((it) => `<option value="${it.providerId}|${it.model}">${esc(it.providerName)} · ${esc(it.model)}</option>`).join('')
    : '<option value="">No capable models enabled yet</option>';
  if (prev && items.some((it) => `${it.providerId}|${it.model}` === prev)) sel.value = prev;
}

const MEM_WIPE = { 'media-images': 'Clear', 'media-videos': 'Clear', 'media-docs': 'Clear', chats: 'Wipe', logs: 'Clear' };
export function renderMemory(stats) {
  const grid = $('#mem-grid');
  if (!grid) return;
  const total = $('#mem-total');
  if (total) total.textContent = stats && stats.memoryOnly ? 'memory-only' : fmtBytes(stats?.totalBytes || 0);
  const cats = Array.isArray(stats?.categories) ? stats.categories : [];
  if (!cats.length) {
    grid.innerHTML = '<div class="empty-state compact"><b>No storage data yet</b><span>Chats, logs and media will show up here.</span></div>';
    return;
  }
  grid.innerHTML = cats.map((cat) => `
    <div class="mem-card">
      <div class="mem-card-head"><b>${esc(cat.label)}</b><span class="count-pill">${fmtBytes(cat.bytes)}</span></div>
      <div class="mem-card-detail">${esc(cat.detail || '')}</div>
      ${MEM_WIPE[cat.id] ? `<div class="mem-card-actions"><button class="btn tiny" data-mem-wipe="${esc(cat.id)}" type="button">${MEM_WIPE[cat.id]}</button></div>` : ''}
    </div>`).join('');
}
