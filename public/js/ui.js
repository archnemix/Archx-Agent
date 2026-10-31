import { canConvertMode } from './chat-lifecycle.mjs';
import { bindLibrary, refreshLibrary } from './memory.js';
/* Archx Agent — screens & controls v4: unified sidebar toggle, auto-refreshing chat debug */

import { $, toast, esc, attachDropdown, attachFilePick } from './dom.js';
import * as api from './api.js';
import {
  state, loadState, newChatRecord, touchChats, touchChat, recordChatDebug, activeChat,
  providerById, activeProfile, activeSystemPrompt, reconcileActiveSelection, modelCaps,
} from './state.js';
import {
  renderSidebar, renderMessages, renderModelUI, renderModelMenu, renderSystemPromptUI, renderSystemPromptSettings,
  setSpEditing, getSpEditing, updateLayoutVars,
  renderSettingsModels, renderSettingsProviders, renderSettingsStorage, renderProfileMenu,
  renderStorageNotes, fillSettings, applyTheme, settingsModelProviderId, setProfileAvailableProvider, toggleModelSelection, selectedModelsFor, clearModelSelection,
  setOpenProfile, editingProfile, renderBranchUI, selectedChats, fillStudioSelect, renderMemory, fmtBytes,
} from './render.js';
import { fetchModelsFor, stop, isStreaming, bindComposer, bindMessageActions, refreshStreamingUI, switchBranch } from './chat.js';
import { markdownReady } from './markdown.js';
import { nextTheme, normalizeTheme } from './theme.mjs';
import { capsFor, CAP_LABEL } from './capabilities.mjs';

let confirmResolver = null;
export function confirmAction({ title = 'Confirm action', message = '', confirmText = 'Continue', danger = true } = {}) {
  const modal = $('#confirm-dialog');
  if (!modal) return Promise.resolve(false);
  if (confirmResolver) confirmResolver(false);
  return new Promise((resolve) => {
    confirmResolver = resolve;
    $('#confirm-title').textContent = title;
    $('#confirm-message').textContent = message;
    $('#confirm-accept').textContent = confirmText;
    $('#confirm-accept').classList.toggle('danger', danger);
    $('#confirm-dialog').classList.remove('hidden');
    $('#confirm-accept').focus();
  });
}

function finishConfirm(value) {
  if (!confirmResolver) return;
  const resolve = confirmResolver;
  confirmResolver = null;
  $('#confirm-dialog').classList.add('hidden');
  resolve(value);
}

async function showPersonalizationOnboarding() {
  const modal = $('#personalization-dialog');
  if (!modal || state.settings.personalizationOnboarded === true) return;
  $('#first-username').value = state.settings.username || '';
  $('#first-age').value = state.settings.age || '';
  $('#first-preferred-name').value = state.settings.preferredName || state.settings.username || '';
  $('#first-agent-name').value = state.settings.agentName || 'Archx Agent';
  modal.classList.remove('hidden');
  $('#first-preferred-name').focus();
}

async function finishPersonalization(save) {
  const modal = $('#personalization-dialog');
  if (!modal) return;
  const patch = save ? {
    username: $('#first-username').value.trim(),
    age: $('#first-age').value.trim(),
    preferredName: $('#first-preferred-name').value.trim(),
    agentName: $('#first-agent-name').value.trim() || 'Archx Agent',
    personalizationOnboarded: true,
  } : { personalizationOnboarded: true };
  try {
    const settings = await api.setSettings(patch);
    state.settings = { ...state.settings, ...settings };
  } catch (err) { toast(err.message, 'err'); return; }
  modal.classList.add('hidden');
  fillSettings();
  renderModelUI();
  renderSystemPromptUI();
}


let modelImportResolver = null;
let modelImportProviderId = null;
let modelImportItems = [];
let modelImportResults = new Map();   // id -> {ok, ms, error, sent, received, reply}
let importRun = null;                 // live run state {stop,done,total,passed,failed,current}

function closeModelImport(result = false) {
  const modal = $('#model-import-dialog');
  if (modal) modal.classList.add('hidden');
  if (modelImportResolver) {
    const resolve = modelImportResolver;
    modelImportResolver = null;
    resolve(result);
  }
}

function renderModelImportDialog(provider, models) {
  const modal = $('#model-import-dialog');
  const list = $('#model-import-list');
  const count = $('#model-import-count');
  const search = $('#model-import-search');
  if (!modal || !list || !provider) return;
  const selected = new Set(modelImportItems.map((m) => m.id));
  const q = (search.value || '').trim().toLowerCase();
  const shown = models.filter((m) => !q || String(m.id || '').toLowerCase().includes(q));
  list.innerHTML = '';
  if (!shown.length) list.innerHTML = '<div class="empty-state compact"><b>No matching new models</b><span>Try another search — models whose id contains the filter text are shown.</span></div>';
  shown.forEach((m) => {
    const r = modelImportResults.get(m.id);
    const testing = importRun && !r;
    const status = testing
      ? '<span class="mini-tag import-testing">queued / testing…</span>'
      : r
        ? (r.ok
          ? `<span class="mini-tag import-ok" title="answered in ${r.ms} ms">✓ works · ${r.ms} ms</span>`
          : `<span class="mini-tag import-bad" title="${esc(r.error || 'failed')}">✗ ${esc((r.error || 'failed').slice(0, 40))}</span>`)
        : '';
    const detail = r && (r.sent || r.received || r.error)
      ? `<details class="import-detail"><summary>request / response</summary><pre>${esc(JSON.stringify({ sent: r.sent || null, received: r.received || r.reply || null, error: r.error || null }, null, 2))}</pre></details>`
      : '';
    const label = document.createElement('label');
    label.className = 'model-import-row' + (r && !r.ok ? ' failed' : '') + (r && r.ok ? ' passed' : '');
    label.innerHTML = `<span class="model-import-main"><span class="model-row-dot ${r?.ok ? 'on' : ''}"></span><span class="model-row-name" title="${esc(m.id)}">${esc(m.id)}</span>${/(^|[:/_-])free$/i.test(m.id || '') ? '<span class="mini-tag free">free</span>' : ''}${m.manual ? '<span class="mini-tag">manual</span>' : ''}${status}</span><input type="checkbox" data-import-model="${esc(m.id)}" ${selected.has(m.id) ? 'checked' : ''} />${detail}`;
    list.appendChild(label);
  });
  const tested = [...modelImportResults.values()].filter((r) => r.ok).length;
  count.textContent = `${modelImportItems.length} new model${modelImportItems.length === 1 ? '' : 's'} found` + (modelImportResults.size ? ` · ${tested} verified working · ${modelImportResults.size - tested} failed` : '');
  const testBtn = $('#model-import-test');
  if (testBtn) { testBtn.disabled = !!importRun || !modelImportItems.length; testBtn.textContent = importRun ? 'Testing…' : 'Test listed models'; }
}

function updateImportProgress() {
  const box = $('#model-import-progress');
  if (!box) return;
  if (!importRun) { box.classList.add('hidden'); return; }
  box.classList.remove('hidden');
  $('#mip-label').textContent = importRun.stop ? 'Stopping…' : 'Testing models in parallel…';
  $('#mip-counts').textContent = `${importRun.done}/${importRun.total} · ${importRun.passed} working · ${importRun.failed} failed · ${importRun.total - importRun.done} remaining`;
  $('#mip-bar').style.width = `${importRun.total ? Math.round((importRun.done / importRun.total) * 100) : 0}%`;
  $('#mip-current').textContent = importRun.current ? `Now probing: ${importRun.current}` : '';
  $('#mip-stop').classList.toggle('hidden', importRun.stop);
}

/* 1.8.0 (issues 1 & 8): live parallel tester. Each model is probed with the
   capability-aware server probe (2 attempts), the panel shows what is being
   tested, what was sent, what came back, how many remain — and a Stop button.
   One single log row per provider is written when the run ends. */
async function runImportTests() {
  const provider = providerById(modelImportProviderId);
  if (!provider || importRun || !modelImportItems.length) return;
  const ids = modelImportItems.map((m) => m.id);
  importRun = { stop: false, done: 0, total: ids.length, passed: 0, failed: 0, current: null };
  modelImportResults = new Map();
  updateImportProgress();
  renderModelImportDialog(provider, modelImportItems);
  const results = [];
  let cursor = 0;
  const worker = async () => {
    for (;;) {
      if (importRun.stop) return;
      const index = cursor++;
      if (index >= ids.length) return;
      const id = ids[index];
      importRun.current = id;
      updateImportProgress();
      let entry;
      try {
        const r = await api.testModelLive(provider.id, { model: id, silent: true, attempts: 2 });
        entry = { model: id, ok: true, ms: r.ms, reply: r.reply, sent: r.sent, received: r.received };
        importRun.passed += 1;
      } catch (err) {
        entry = { model: id, ok: false, error: err.message };
        importRun.failed += 1;
      }
      modelImportResults.set(id, entry);
      results.push(entry);
      importRun.done += 1;
      updateImportProgress();
      renderModelImportDialog(provider, modelImportItems);
    }
  };
  await Promise.all(Array.from({ length: Math.min(8, ids.length) }, () => worker()));
  const stopped = importRun.stop;
  importRun = null;
  api.logBatchTest(provider.id, { results, stopped }).catch(() => {});
  // failed models get unchecked so the check-list mirrors reality; passed and
  // untested models stay checked (they are what "Add checked models" sends).
  document.querySelectorAll('#model-import-list [data-import-model]').forEach((x) => {
    const r = modelImportResults.get(x.dataset.importModel);
    if (r && !r.ok) x.checked = false;
  });
  updateImportProgress();
  renderModelImportDialog(provider, modelImportItems);
  toast(stopped
    ? `Stopped at ${results.length}/${ids.length}: ${importRunCount(results, true)} working. Untested models remain checked.`
    : `Tested ${results.length} models in parallel: ${results.filter((r) => r.ok).length} working, ${results.filter((r) => !r.ok).length} failed.`, 'ok', 4600);
}
const importRunCount = (results, ok) => results.filter((r) => !!r.ok === ok).length;

function openModelImportDialog(provider, models) {
  const modal = $('#model-import-dialog');
  if (!modal) return Promise.resolve(false);
  modelImportProviderId = provider.id;
  modelImportItems = Array.from(new Map(models.filter((m) => m && m.id).map((m) => [m.id, m])).values());
  modelImportResults = new Map();
  importRun = null;
  updateImportProgress();
  $('#model-import-title').textContent = `Add models from ${provider.name}`;
  $('#model-import-subtitle').textContent = provider.models?.catalogInitialized ? 'These are models the provider exposes that are not in your list yet. Test them first and add only the ones that work.' : 'Choose exactly which models should be added to your local list. Unchecked models are not added.';
  $('#model-import-search').value = '';
  $('#model-import-select-all').textContent = 'Select all';
  $('#model-import-none').textContent = 'Clear all';
  const manualInput = $('#model-import-manual-input');
  if (manualInput) manualInput.value = '';
  renderModelImportDialog(provider, modelImportItems);
  modal.classList.remove('hidden');
  $('#model-import-search').focus();
  // 1.8.0 (issue 1): "add only working models" kicks the live tester off automatically
  if ($('#model-import-only-working')?.checked) setTimeout(() => runImportTests(), 60);
  return new Promise((resolve) => { modelImportResolver = resolve; });
}

async function addSelectedProviderModels() {
  const provider = providerById(modelImportProviderId);
  if (!provider) return closeModelImport(false);
  let selected = [...document.querySelectorAll('#model-import-list [data-import-model]:checked')].map((x) => x.dataset.importModel);
  // 1.8.0 (issue 1): "Add only working models" adds tested-and-passing models
  // plus models that were never tested (e.g. run stopped early) — only models
  // that were tested and REJECTED are dropped.
  if ($('#model-import-only-working')?.checked && modelImportResults.size) {
    selected = selected.filter((id) => {
      const r = modelImportResults.get(id);
      return !r || r.ok;
    });
  }
  const manualIds = new Set(modelImportItems.filter((m) => m.manual).map((m) => m.id));
  const catalog = new Set(provider.models.catalog || []);
  const custom = new Set(provider.models.custom || []);
  selected.forEach((id) => { catalog.add(id); if (manualIds.has(id)) custom.add(id); });
  const next = { ...provider.models, catalog: [...catalog], custom: [...custom], catalogInitialized: true, selectionMode: 'checklist' };
  try {
    const body = await api.patchProvider(provider.id, { models: next });
    state.providers = state.providers.map((p) => p.id === body.provider.id ? body.provider : p);
    renderSettingsModels();
    renderModelUI();
    closeModelImport(true);
    toast(selected.length ? `Added ${selected.length} model${selected.length === 1 ? '' : 's'} to ${provider.name}.` : 'No models added. You can fetch again later.', 'ok', 2400);
  } catch (err) { toast(err.message, 'err'); }
}

async function fetchModelsFromProvider({ interactive = true } = {}) {
  const pid = settingsModelProviderId();
  const provider = providerById(pid);
  if (!provider) return toast('Choose a provider first.', 'err');
  const btn = $('#mdl-fetch');
  if (btn) { btn.disabled = true; btn.textContent = 'Fetching…'; }
  try {
    const list = await fetchModelsFor(pid, { silent: true, force: true });
    const current = providerById(pid);
    const catalog = new Set(current?.models?.catalog || []);
    const missing = list.filter((m) => m?.id && !catalog.has(m.id));
    renderSettingsModels();
    if (interactive) {
      if (!missing.length) toast(`${current.name}: no new models found (${list.length} exposed).`, 'ok', 2200);
      else await openModelImportDialog(current, missing);
    }
  } catch (err) { toast(err.message, 'err'); }
  finally { if (btn) { btn.disabled = false; btn.textContent = 'Fetch models'; } }
}

/* Provider presets: the user picks a known provider (which fills name, base
   URL and the right adapter) or stays on Custom and types anything. Every
   field stays editable — presets are starters, not straitjackets. Keyless
   local servers are first-class citizens. */
const PROVIDER_PRESETS = [
  { id: 'anthropic', label: 'Anthropic (Claude)', url: 'https://api.anthropic.com/v1', adapter: 'anthropic' },
  { id: 'gemini', label: 'Google Gemini', url: 'https://generativelanguage.googleapis.com/v1beta', adapter: 'gemini' },
  { id: 'openrouter', label: 'OpenRouter', url: 'https://openrouter.ai/api/v1', adapter: 'openai-compatible' },
  { id: 'groq', label: 'Groq', url: 'https://api.groq.com/openai/v1', adapter: 'openai-compatible' },
  { id: 'nvidia-nim', label: 'NVIDIA NIM', url: 'https://integrate.api.nvidia.com/v1', adapter: 'nvidia-nim' },
  { id: 'openai', label: 'OpenAI', url: 'https://api.openai.com/v1', adapter: 'openai-compatible' },
  { id: 'deepseek', label: 'DeepSeek', url: 'https://api.deepseek.com/v1', adapter: 'openai-compatible' },
  { id: 'mistral', label: 'Mistral', url: 'https://api.mistral.ai/v1', adapter: 'openai-compatible' },
  { id: 'together', label: 'Together AI', url: 'https://api.together.xyz/v1', adapter: 'openai-compatible' },
  { id: 'ollama', label: 'Ollama · local · no key', url: 'http://localhost:11434/v1', adapter: 'openai-compatible', keyless: true },
  { id: 'lmstudio', label: 'LM Studio · local · no key', url: 'http://localhost:1234/v1', adapter: 'openai-compatible', keyless: true },
  { id: 'vllm', label: 'vLLM · local · no key', url: 'http://localhost:8000/v1', adapter: 'openai-compatible', keyless: true },
];
const PRESETS = PROVIDER_PRESETS.map((p) => [p.label, p.url]);
const ADAPTER_DEFAULT_BASE = {
  anthropic: 'https://api.anthropic.com/v1',
  gemini: 'https://generativelanguage.googleapis.com/v1beta',
};
const CHIPS = ['Explain how SSE streaming works', 'Write a regex that matches semver tags', 'Compare SQL joins with a table', 'Give me a 5-line python http server', 'Think step by step: is 9.11 bigger than 9.9?'];

let menuProvId = null;
let serverVersion = '';
let logTimer = null;
let logCache = [];
let logCacheSig = '';
let logRev = 0;                 // journal revision from the server (poll cheaply)
let searchBlob = new Map();     // logId -> lowercase JSON, built once per fetch
const expandedLogs = new Set();
const logDetailScroll = new Map();
let logVisible = 2000;
let logCategory = 'all';

let chatDebugOpen = false;
let chatDebugTab = 'api';
let chatDebugData = { apiCalls: [], tools: [], other: [], providers: [] };
let chatDebugTimer = null;
let chatDebugRev = -1;
let chatDebugLocalRev = -1;

function formatDebugEvent(e) {
  const t = (e.ts || '').slice(11, 19);
  const label = e.label || e.kind || 'event';
  const detail = e.error || (e.detail && e.detail.error) || '';
  return `<article class="chat-debug-item" data-log-id="${esc(logId(e))}"><div><span class="dbg-time">${esc(t)}</span><b>${esc(label)}</b></div>${detail ? `<div class="chat-debug-error">${esc(detail)}</div>` : ''}<pre>${esc(JSON.stringify(e.detail ?? e, null, 2))}</pre></article>`;
}

async function loadChatDebug() {
  const chat = activeChat();
  const list = $('#chat-debug-list');
  if (!chat) { list.innerHTML = '<div class="dbg-empty">Start or select a chat first.</div>'; return; }
  try {
    const data = await api.getChatDebug({ traceIds: chat.debugTraceIds || [], chatId: chat.id });
    chatDebugData = data;
    chatDebugRev = Number(data.rev || 0);
    $('#chat-debug-sub').textContent = `${chat.title} · provider calls and local activity`;
    $('#chat-debug-api-count').textContent = String((data.apiCalls || []).length);
    $('#chat-debug-tools-count').textContent = String((data.tools || []).length);
    const other = [...(data.other || []), ...(chat.debugEvents || [])];
    $('#chat-debug-other-count').textContent = String(other.length);
    const provSel = $('#chat-debug-provider');
    const current = provSel.value;
    provSel.innerHTML = '<option value="">All providers</option>';
    (data.providers || []).forEach((p) => { const o = document.createElement('option'); o.value = p; o.textContent = p; provSel.appendChild(o); });
    provSel.value = (data.providers || []).includes(current) ? current : '';
    renderChatDebug();
  } catch (err) {
    list.innerHTML = `<div class="dbg-empty">Chat debug unavailable: ${esc(err.message)}</div>`;
  }
}

/*
 * Chat-debug repaint policy (1.6.6):
 *  1. If the row set is byte-identical to the last paint, do nothing at all —
 *     a 3s auto-refresh must never touch the DOM (or the scroll position) when
 *     nothing changed.
 *  2. When rows did change, restore the reader's anchor by ENTRY ID, not by
 *     pixel offset: remember which entry sat at the top of the viewport and
 *     how far into it we were, then re-place that same entry after the repaint.
 *     Pixel-only restore drifts whenever an entry above grows (a streaming
 *     request gaining usage/ms fields), which is exactly the "it jumps to the
 *     top of the request I was reading" bug.
 */
let lastChatDebugSig = null;
function renderChatDebug() {
  const list = $('#chat-debug-list');
  if (!list) return;
  let rows = [];
  if (chatDebugTab === 'api') {
    const provider = $('#chat-debug-provider').value;
    rows = (chatDebugData.apiCalls || []).filter((e) => !provider || e.provider === provider || e.providerId === provider);
  } else if (chatDebugTab === 'tools') {
    rows = chatDebugData.tools || [];
  } else {
    rows = [...(chatDebugData.other || []), ...(activeChat()?.debugEvents || [])];
  }
  const sig = chatDebugTab + '|' + ($('#chat-debug-provider')?.value || '') + '|' + JSON.stringify(rows.map((r) => logId(r)));
  if (sig === lastChatDebugSig) return;
  const prev = [...list.children].find((el) => el.dataset.logId && el.offsetTop + el.offsetHeight > list.scrollTop + 4);
  const anchorId = prev ? prev.dataset.logId : null;
  const anchorOff = prev ? list.scrollTop - prev.offsetTop : 0;
  lastChatDebugSig = sig;
  list.innerHTML = rows.length ? rows.map(formatDebugEvent).join('') : '<div class="dbg-empty">No activity recorded in this category.</div>';
  if (anchorId) {
    const el = list.querySelector(`[data-log-id="${CSS.escape(anchorId)}"]`);
    if (el) list.scrollTop = el.offsetTop + anchorOff;
  }
}

function toggleChatDebug(force) {
  chatDebugOpen = force == null ? !chatDebugOpen : !!force;
  const pop = $('#chat-debug-pop');
  pop.classList.toggle('hidden', !chatDebugOpen);
  pop.setAttribute('aria-hidden', String(!chatDebugOpen));
  // Reserve horizontal space so the panel never covers the conversation.
  const page = $('#page-chat');
  if (page) page.classList.toggle('dbg-open', chatDebugOpen);
  // Paint from cache first so the panel appears instantly; refresh after.
  if (chatDebugOpen) {
    chatDebugRev = -1;
    chatDebugLocalRev = -1;
    renderChatDebug();
    loadChatDebug();
  }
}
function refreshChatDebugIfOpen() { if (chatDebugOpen) { chatDebugRev = -1; loadChatDebug(); } }
function startChatDebugAutoRefresh() {
  if (chatDebugTimer) return;
  chatDebugTimer = setInterval(async () => {
    if (!chatDebugOpen || document.hidden || document.body.dataset.page !== 'chat') return;
    // Revision probe first: a 3 s poll must not ship hundreds of log payloads
    // when nothing happened.
    try {
      const rev = await api.getLogsRev();
      const chat = activeChat();
      const localRev = chat ? (chat.debugEvents || []).length + (chat.debugTraceIds || []).length : 0;
      if (Number(rev.rev || 0) === chatDebugRev && localRev === chatDebugLocalRev) return;
      chatDebugLocalRev = localRev;
    } catch { /* fall through to a full load */ }
    loadChatDebug();
  }, 3000);
}
export { refreshChatDebugIfOpen };

export function showPage(page, sec) {
  const known = ['chat', 'studio', 'memory', 'settings', 'debug'];
  const p = known.includes(page) ? page : 'chat';
  known.forEach((k) => $('#page-' + k).classList.toggle('hidden', k !== p));
  document.body.dataset.page = p;
  updateLayoutVars();
  document.querySelectorAll('.page-nav-btn').forEach((b) => b.classList.toggle('active', b.dataset.page === p));
  if (p === 'settings') { fillSettings(); fillToolsSettings(); setSec(sec || 'general'); }
  else if (p === 'debug') { loadLogs(); startLogAutoRefresh(); }
  else if (p === 'studio') { renderStudio(); }
  else if (p === 'memory') { loadMemoryStats(); }
  else {
    // Returning to Chat with the panel open: paint cached rows immediately,
    // then refresh in the background — no empty-flash latency.
    if (chatDebugOpen) { renderChatDebug(); refreshChatDebugIfOpen(); }
    $('#input').focus();
  }
}
function setSec(sec) {
  document.querySelectorAll('.set-nav-btn').forEach((b) => b.classList.toggle('active', b.dataset.sec === sec));
  document.querySelectorAll('.set-page').forEach((s) => s.classList.add('hidden'));
  const el = $('#sec-' + sec);
  if (el) el.classList.remove('hidden');
  if (sec === 'providers') setTimeout(() => {
    $('#prov-form')?.classList.remove('hidden');
    const ad = $('#prov-adapter');
    if (ad.options.length !== (state.providerAdapters || []).length) setProviderEditorMode($('#prov-edit-id').value || '');
  }, 0);
  if (sec === 'models') setTimeout(() => ensureSettingsModelsLoaded(), 0);
  // 1.7.0: the Profiles page lists "available to add" models, so warm the
  // (cached, deduped) model lists on entry — the Fetch button lives on Models.
  if (sec === 'profiles') setTimeout(() => { ensureAllProfileModelsLoaded().then(renderSettingsModels).catch(() => {}); }, 0);
}
export function openSettings(sec) { location.hash = sec ? '#/settings:' + sec : '#/settings'; showPage('settings', sec || 'general'); }
function route() { const raw = location.hash.replace(/^#\/?/, ''); const [page, sec] = raw.split(':'); showPage(page || 'chat', sec); }

function setProviderEditorMode(id = '') {
  const editing = !!id, p = editing ? providerById(id) : null;
  $('#prov-edit-id').value = editing ? id : '';
  $('#prov-form-title').textContent = editing ? `Edit provider — ${p?.name || ''}` : 'Add provider';
  $('#prov-name').value = p?.name || '';
  $('#prov-url').value = p?.baseUrl || '';
  const adapter = $('#prov-adapter');
  if (adapter) {
    adapter.innerHTML = '';
    for (const id of (state.providerAdapters || ['openai-compatible'])) {
      const option = document.createElement('option');
      option.value = id;
      option.textContent = id;
      adapter.appendChild(option);
    }
    adapter.value = p?.adapter || 'openai-compatible';
    if (!adapter.value && adapter.options.length) adapter.selectedIndex = 0;
  }
  const presetSel = $('#prov-preset');
  if (presetSel) {
    presetSel.innerHTML = '<option value="">Custom…</option>';
    PROVIDER_PRESETS.forEach((pr) => {
      const o = document.createElement('option');
      o.value = pr.id;
      o.textContent = pr.label;
      presetSel.appendChild(o);
    });
    // show which known provider this entry is (by URL, else by name) so the
    // choice is always visible and always changeable while editing
    presetSel.value = editing
      ? (PROVIDER_PRESETS.find((x) => x.url === p?.baseUrl || x.label.split(' ·')[0].toLowerCase() === String(p?.name || '').toLowerCase())?.id || '')
      : '';
  }
  $('#prov-key').value = '';
  $('#prov-key-hint').textContent = editing ? (p?.hasKey ? `Stored key: ${p.keyMasked}. Leave blank to keep it.` : 'No key stored.') : 'Keys are encrypted at rest. Local servers work with no key at all.';
  $('#prov-status').textContent = '';
  $('#prov-test').disabled = !editing && !$('#prov-url').value.trim();
  $('#prov-cancel').classList.toggle('hidden', !editing);
  $('#prov-form').classList.remove('hidden');
}
function resetProviderEditor(focus = true) { setProviderEditorMode(''); if (focus) setTimeout(() => $('#prov-url').focus(), 30); }
function editProviderInline(id) { if (!providerById(id)) return; setProviderEditorMode(id); $('#prov-form').scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
function focusProviderEditor(reset = true) { if (reset) resetProviderEditor(false); }
/* Apply a preset: fills URL + adapter (and the name when it is still empty
   or still a preset name). The fields remain fully editable afterwards. */
function applyProviderPreset(id) {
  const pr = PROVIDER_PRESETS.find((x) => x.id === id);
  if (!pr) return;
  $('#prov-url').value = pr.url;
  const adapter = $('#prov-adapter');
  if (adapter && [...adapter.options].some((o) => o.value === pr.adapter)) adapter.value = pr.adapter;
  const name = $('#prov-name');
  const untouched = !name.value.trim() || PROVIDER_PRESETS.some((x) => x.label.split(' ·')[0] === name.value.trim());
  if (untouched) name.value = pr.label.split(' ·')[0];
  $('#prov-test').disabled = false;
  $('#prov-status').textContent = pr.keyless ? 'Local endpoint — no API key needed.' : '';
}
async function testProviderInline() {
  recordChatDebug('other', 'Provider test requested');
  const id = $('#prov-edit-id').value, url = $('#prov-url').value.trim(), key = $('#prov-key').value.trim();
  if (id) {
    try {
      if (key) { const body = await api.patchProvider(id, { apiKey: key }); state.providers = state.providers.map((p) => p.id === id ? body.provider : p); renderSettingsProviders(); }
      $('#prov-status').textContent = 'Testing…';
      const r = await api.testProvider(id);
      $('#prov-status').textContent = `Reachable · ${r.modelCount} models · ${r.ms} ms`;
      toast('Provider reachable.', 'ok');
    } catch (e) { $('#prov-status').textContent = 'Unreachable: ' + e.message; toast(e.message, 'err'); }
    return;
  }
  if (!url) { $('#prov-status').textContent = 'Enter a base URL first.'; return; }
  try {
    $('#prov-status').textContent = 'Testing…';
    const r = await api.testProviderDraft({ baseUrl: url, apiKey: key || undefined, adapter: $('#prov-adapter').value || 'openai-compatible' });
    $('#prov-status').textContent = `Reachable · ${r.modelCount} models · ${r.ms} ms`;
    toast('Provider reachable.', 'ok');
  } catch (e) { $('#prov-status').textContent = 'Unreachable: ' + e.message; toast(e.message, 'err'); }
}
async function saveProviderInline() {
  recordChatDebug('other', 'Provider save requested', { providerId: $('#prov-edit-id').value || null });
  const editId = $('#prov-edit-id').value, name = $('#prov-name').value.trim(), url = $('#prov-url').value.trim(), key = $('#prov-key').value.trim();
  if (!url) { $('#prov-status').textContent = 'Endpoint base URL is required.'; return; }
  const btn = $('#prov-save');
  btn.disabled = true;
  try {
    let body, id;
    if (editId) {
      const patch = { name: name || undefined, baseUrl: url, adapter: $('#prov-adapter').value || 'openai-compatible' };
      if (key) patch.apiKey = key;
      body = await api.patchProvider(editId, patch);
      state.providers = state.providers.map((p) => p.id === editId ? body.provider : p);
      id = editId;
    } else {
      body = await api.addProvider({ name, baseUrl: url, apiKey: key || undefined, adapter: $('#prov-adapter').value || 'openai-compatible' });
      state.providers = [...state.providers, body.provider];
      state.active = body.active;
      id = body.provider.id;
    }
    renderSettingsProviders();
    renderSettingsModels();
    renderModelUI();
    renderSidebar();
    renderMessages();
    let fetched = [];
    try { fetched = await fetchModelsFor(id, { silent: true }); renderSettingsModels(); } catch { /* ignore */ }
    if (editId) { $('#prov-status').textContent = 'Saved changes.'; toast(`Updated ${body.provider.name}.`, 'ok'); }
    else {
      const addedName = body.provider.name;
      const savedProvider = providerById(id);
      if (savedProvider?.models?.selectionMode === 'checklist' && !savedProvider.models.catalogInitialized && fetched.length) {
        await openModelImportDialog(savedProvider, fetched);
      }
      resetProviderEditor(false);
      $('#prov-status').textContent = `Added ${addedName}. Ready for another provider.`;
      toast(`Added ${addedName}. You can add another provider without refreshing.`, 'ok', 3200);
    }
  } catch (e) { $('#prov-status').textContent = e.message || String(e); toast(e.message, 'err'); }
  finally { btn.disabled = false; }
}

function saveSystemPromptSettings() {
  return api.setSettings({ systemPrompts: state.settings.systemPrompts, defaultSystemPromptId: state.settings.defaultSystemPromptId, system: state.settings.system || '' }).then((x) => { if (x) state.settings = { ...state.settings, ...(x.settings || x) }; return x; });
}
/* ── provider delete with model policy (1.8.0, issue 5) ─────── */
let pendingProviderDelete = null;
function openProviderDeleteDialog(id) {
  const p = providerById(id);
  pendingProviderDelete = id;
  $('#pd-message').textContent = `Delete provider ${p ? p.name : id} and its stored key?`;
  $('#provider-delete-dialog').classList.remove('hidden');
}
async function finishProviderDelete(policy) {
  const id = pendingProviderDelete;
  $('#provider-delete-dialog').classList.add('hidden');
  if (!id) return;
  pendingProviderDelete = null;
  try {
    recordChatDebug('other', 'Provider removed', { providerId: id, policy });
    const body = await api.deleteProvider(id, policy);
    state.providers = body.providers;
    state.active = body.active;
    state.profiles = body.profiles || state.profiles;
    state.activeProfileId = body.activeProfileId || null;
    delete state.providerModels[id];
    renderSettingsProviders(); renderSettingsModels(); renderModelUI(); renderSidebar(); renderMessages(); renderProfileMenu();
    toast(policy === 'pause' ? 'Provider deleted — its profile models were kept paused; re-attach the provider to restore them.' : 'Provider and its models removed.', 'ok', 5200);
  } catch (e) { toast(e.message, 'err'); }
}

/* ── generic name/details dialog (1.8.0, issue 9) ──────────── */
let nameDialogResolver = null;
function askName({ title, sub = '', initial = '', desc = '', showDesc = true, showEnable = false, enableLabel = 'Activate it now', enableDefault = false, okText = 'Create' } = {}) {
  $('#name-dialog-title').textContent = title;
  $('#name-dialog-sub').textContent = sub;
  $('#name-dialog-name').value = initial;
  $('#name-dialog-desc-wrap').classList.toggle('hidden', !showDesc);
  $('#name-dialog-desc').value = desc;
  $('#name-dialog-enable-wrap').classList.toggle('hidden', !showEnable);
  $('#name-dialog-enable').checked = enableDefault;
  $('#name-dialog-enable-label').textContent = enableLabel;
  $('#name-dialog-ok').textContent = okText;
  $('#name-dialog').classList.remove('hidden');
  setTimeout(() => { $('#name-dialog-name').focus(); $('#name-dialog-name').select(); }, 30);
  return new Promise((resolve) => { nameDialogResolver = resolve; });
}
function finishNameDialog(value) {
  $('#name-dialog').classList.add('hidden');
  if (!nameDialogResolver) return;
  const r = nameDialogResolver;
  nameDialogResolver = null;
  r(value);
}

/* ── studio (1.8.0, issue 2) ────────────────────────────────── */
const studioSel = { image: null, tts: null, stt: null, vision: null };
function renderStudio() {
  fillStudioSelect($('#si-model'), 'imageGen', studioSel.image);
  fillStudioSelect($('#st-model'), 'tts', studioSel.tts);
  fillStudioSelect($('#sr-model'), 'stt', studioSel.stt);
  fillStudioSelect($('#sv-model'), 'vision', studioSel.vision);
}
const readStudioPick = (sel) => {
  const v = sel.value;
  if (!v) return null;
  const i = v.indexOf('|');
  return { providerId: v.slice(0, i), model: v.slice(i + 1) };
};
const fileToB64 = (file) => new Promise((resolve, reject) => {
  const r = new FileReader();
  r.onload = () => resolve({ base64: String(r.result).split(',')[1], mime: file.type || 'application/octet-stream' });
  r.onerror = () => reject(new Error('Could not read the file.'));
  r.readAsDataURL(file);
});
function studioStatus(id, txt) { const el = $(id); if (el) el.textContent = txt || ''; }

async function studioImageRun() {
  const pick = readStudioPick($('#si-model'));
  const prompt = $('#si-prompt').value.trim();
  if (!pick) return toast('Enable an image-generation model first (Settings → Models).', 'err');
  if (!prompt) return toast('Describe the image first.', 'err');
  studioSel.image = $('#si-model').value;
  const refFile = $('#si-ref').files?.[0];
  let ref = null;
  if (refFile) ref = await fileToB64(refFile);
  const btn = $('#si-run');
  btn.disabled = true;
  studioStatus('#si-status', 'Generating…');
  try {
    const r = await api.generateImage(pick.providerId, { model: pick.model, prompt, image: ref?.base64, imageMime: ref?.mime });
    $('#si-out').innerHTML = `<div class="studio-result"><img alt="Generated image" src="data:${r.mime};base64,${r.base64}" /><div class="studio-result-meta"><span>${esc(pick.model)} · ${Math.round((r.ms || 0) / 100) / 10}s</span><a class="btn tiny" download="archx-image.png" href="data:${r.mime};base64,${r.base64}">Download</a></div>${r.revisedPrompt ? `<p class="hint">${esc(r.revisedPrompt)}</p>` : ''}</div>`;
    studioStatus('#si-status', 'Done.');
  } catch (e) {
    studioStatus('#si-status', '');
    toast(e.message, 'err', 6000);
  } finally { btn.disabled = false; }
}

async function studioTtsRun() {
  const pick = readStudioPick($('#st-model'));
  const input = $('#st-input').value.trim();
  if (!pick) return toast('Enable a text-to-speech model first.', 'err');
  if (!input) return toast('Type the text to speak first.', 'err');
  studioSel.tts = $('#st-model').value;
  $('#st-run').disabled = true;
  studioStatus('#st-status', 'Synthesizing…');
  try {
    const r = await api.speech(pick.providerId, { model: pick.model, input, voice: $('#st-voice').value.trim() || undefined });
    const mime = /audio\//.test(r.mime) ? r.mime : 'audio/mpeg';
    $('#st-out').innerHTML = `<div class="studio-result"><audio controls src="data:${mime};base64,${r.base64}"></audio><div class="studio-result-meta"><span>${esc(pick.model)} · ${Math.round((r.ms || 0) / 100) / 10}s</span><a class="btn tiny" download="archx-speech.${mime.includes('wav') ? 'wav' : 'mp3'}" href="data:${mime};base64,${r.base64}">Download</a></div></div>`;
    studioStatus('#st-status', 'Done.');
  } catch (e) { studioStatus('#st-status', ''); toast(e.message, 'err', 6000); }
  finally { $('#st-run').disabled = false; }
}

async function studioSttRun() {
  const pick = readStudioPick($('#sr-model'));
  const file = $('#sr-file').files?.[0];
  if (!pick) return toast('Enable a speech-to-text model first.', 'err');
  if (!file) return toast('Choose an audio file first.', 'err');
  studioSel.stt = $('#sr-model').value;
  $('#sr-run').disabled = true;
  studioStatus('#sr-status', 'Transcribing…');
  try {
    const { base64, mime } = await fileToB64(file);
    const r = await api.transcribe(pick.providerId, { model: pick.model, audio: base64, mime });
    $('#sr-out').innerHTML = `<div class="studio-result"><pre class="studio-text">${esc(r.text || '(empty transcription)')}</pre><div class="studio-result-meta"><span>${esc(pick.model)} · ${Math.round((r.ms || 0) / 100) / 10}s</span><button class="btn tiny" id="sr-copy" type="button">Copy</button></div></div>`;
    $('#sr-copy')?.addEventListener('click', () => navigator.clipboard?.writeText(r.text || '').then(() => toast('Transcription copied.', 'ok', 1400)));
    studioStatus('#sr-status', 'Done.');
  } catch (e) { studioStatus('#sr-status', ''); toast(e.message, 'err', 6000); }
  finally { $('#sr-run').disabled = false; }
}

async function studioVisionRun() {
  const pick = readStudioPick($('#sv-model'));
  const files = [...($('#sv-file').files || [])];
  const prompt = $('#sv-prompt').value.trim() || 'Extract all text from these images (OCR). Output only the extracted text.';
  if (!pick) return toast('Enable a vision model first.', 'err');
  if (!files.length) return toast('Choose at least one image first.', 'err');
  studioSel.vision = $('#sv-model').value;
  $('#sv-run').disabled = true;
  studioStatus('#sv-status', `Reading ${files.length} image${files.length > 1 ? 's' : ''}…`);
  try {
    const parts = [{ type: 'text', text: prompt }];
    for (const f of files) {
      const { base64, mime } = await fileToB64(f);
      parts.push({ type: 'image_url', image_url: { url: `data:${mime};base64,${base64}` } });
    }
    const text = await api.chat({
      providerId: pick.providerId, model: pick.model, stream: false,
      messages: [{ role: 'user', content: parts }],
    });
    $('#sv-out').innerHTML = `<div class="studio-result"><pre class="studio-text">${esc(text || '(no output)')}</pre><div class="studio-result-meta"><span>${esc(pick.model)}</span><button class="btn tiny" id="sv-copy" type="button">Copy</button></div></div>`;
    $('#sv-copy')?.addEventListener('click', () => navigator.clipboard?.writeText(text || '').then(() => toast('Result copied.', 'ok', 1400)));
    studioStatus('#sv-status', 'Done.');
  } catch (e) { studioStatus('#sv-status', ''); toast(e.message, 'err', 6000); }
  finally { $('#sv-run').disabled = false; }
}

/* ── memory page (1.8.0, issue 13) ─────────────────────────── */
async function loadMemoryStats() {
  void refreshLibrary();
  try {
    const s = await api.memoryStats();
    renderMemory(s);
  } catch (e) {
    $('#mem-grid').innerHTML = `<div class="empty-state compact"><b>Stats unavailable</b><span>${esc(e.message)}</span></div>`;
  }
}

/* ── probe dialog (1.8.0, issue 7) ─────────────────────────── */
import { defaultTestBodyFor } from './capabilities.mjs';
let probeCtx = null;
function openProbeDialog(providerId, model) {
  const p = providerById(providerId);
  if (!p) return;
  probeCtx = { providerId, model };
  const caps = modelCaps(providerId, model);
  $('#probe-title').textContent = `Probe — ${model}`;
  $('#probe-sub').textContent = `${p.name} · tests exercise the surface the model advertises`;
  const box = $('#probe-caps');
  box.innerHTML = '';
  for (const [k, v] of Object.entries(caps)) {
    const l = document.createElement('label');
    l.className = 'check';
    l.innerHTML = `<input type="checkbox" data-probe-cap="${k}" ${v ? 'checked' : ''} /> ${CAP_LABEL[k] || k}`;
    box.appendChild(l);
  }
  const saved = p.models?.testBodies?.[model];
  $('#probe-body').value = saved ? JSON.stringify(saved, null, 2) : '';
  $('#probe-default').textContent = JSON.stringify(defaultTestBodyFor(model, caps), null, 2);
  $('#probe-result').textContent = '';
  $('#probe-dialog').classList.remove('hidden');
}
async function saveProbe() {
  if (!probeCtx) return;
  const { providerId, model } = probeCtx;
  const p = providerById(providerId);
  if (!p) return;
  const caps = {};
  document.querySelectorAll('[data-probe-cap]').forEach((c) => { caps[c.dataset.probeCap] = c.checked; });
  let body;
  const raw = $('#probe-body').value.trim();
  if (raw) {
    try { body = JSON.parse(raw); } catch { return toast('Custom test body is not valid JSON.', 'err'); }
  }
  const models = { ...p.models, capabilities: { ...(p.models?.capabilities || {}), [model]: caps }, testBodies: { ...(p.models?.testBodies || {}) } };
  if (body) models.testBodies[model] = body; else delete models.testBodies[model];
  try {
    const out = await api.patchProvider(providerId, { models });
    state.providers = state.providers.map((x) => x.id === providerId ? out.provider : x);
    renderSettingsModels();
    toast(`Saved probe settings for ${model}.`, 'ok', 2000);
  } catch (e) { toast(e.message, 'err'); }
}
async function runProbeNow() {
  if (!probeCtx) return;
  const { providerId, model } = probeCtx;
  $('#probe-result').textContent = 'Testing…';
  try {
    const r = await api.testModelLive(providerId, { model });
    $('#probe-result').textContent = JSON.stringify({ ok: true, probe: r.probe, ms: r.ms, sent: r.sent, received: r.received, reply: r.reply }, null, 2);
  } catch (e) {
    $('#probe-result').textContent = JSON.stringify({ ok: false, error: e.message }, null, 2);
  }
}

/* ── search engines + retention UI (1.8.0) ─────────────────── */
const ENGINE_LABEL = { ddg: 'DuckDuckGo (free)', bing: 'Bing (free)', searxng: 'SearXNG (free)' };
function renderSearchEngines() {
  const cfg = state.settings.search || { engines: ['ddg', 'bing', 'searxng'] };
  const box = $('#search-engine-list');
  if (!box) return;
  box.innerHTML = '';
  cfg.engines.forEach((id, i) => {
    const row = document.createElement('div');
    row.className = 'engine-row';
    row.innerHTML = `<span class="engine-rank">${i + 1}</span><b>${esc(ENGINE_LABEL[id] || id)}</b><span class="engine-actions"><button class="btn tiny" type="button" data-eng-up="${i}" ${i === 0 ? 'disabled' : ''}>↑</button><button class="btn tiny" type="button" data-eng-down="${i}" ${i === cfg.engines.length - 1 ? 'disabled' : ''}>↓</button></span>`;
    box.appendChild(row);
  });
}
function saveSearchSettings(patch) {
  const cur = state.settings.search || { enabled: true, engines: ['ddg', 'bing', 'searxng'], maxResults: 5 };
  const next = { ...cur, ...patch };
  state.settings.search = next;
  api.setSettings({ search: next }).catch(() => {});
  renderSearchEngines();
}
function fillToolsSettings() {
  const sc = state.settings.search || { enabled: true, engines: ['ddg', 'bing', 'searxng'], maxResults: 5 };
  const se = $('#set-search-enabled'); if (se) se.checked = sc.enabled !== false;
  const sm = $('#set-search-max'); if (sm) sm.value = sc.maxResults || 5;
  renderSearchEngines();
  const lr = state.settings.logRetention || {};
  $('#ret-api').value = lr.apiDays ?? '';
  $('#ret-tools').value = lr.toolsDays ?? '';
  $('#ret-config').value = lr.configDays ?? '';
  $('#ret-all').value = lr.allDays ?? '';
}
function saveRetention() {
  const numOrNull = (v) => { const n = Number(v); return Number.isFinite(n) && n > 0 ? n : null; };
  const patch = { logRetention: { apiDays: numOrNull($('#ret-api').value), toolsDays: numOrNull($('#ret-tools').value), configDays: numOrNull($('#ret-config').value), allDays: numOrNull($('#ret-all').value) } };
  state.settings.logRetention = patch.logRetention;
  api.setSettings(patch).then(() => toast('Log retention saved — applied at startup and every 6 h.', 'ok', 2600)).catch((e) => toast(e.message, 'err'));
}

/* ── sidebar toggle (single button, works on desktop + mobile) ─ */
function toggleSidebar(force) {
  const mobile = window.innerWidth <= 860;
  if (mobile) {
    const next = force === undefined ? !document.body.classList.contains('side-open') : !!force;
    document.body.classList.toggle('side-open', next);
  } else {
    const next = force === undefined ? !document.body.classList.contains('side-hidden') : !force;
    document.body.classList.toggle('side-hidden', next);
  }
  const btn = $('#side-toggle');
  if (btn) {
    const expanded = mobile ? document.body.classList.contains('side-open') : !document.body.classList.contains('side-hidden');
    btn.setAttribute('aria-expanded', String(expanded));
  }
}
function closeSidebarIfMobile() { if (window.innerWidth <= 860) toggleSidebar(false); }

/* ── model menu ──────────────────────────────────────────── */
function ensureLoaded(id) {
  if (!state.providerModels[id]) {
    fetchModelsFor(id, { silent: true }).then(() => renderModelMenu(menuProvId)).catch(() => renderModelMenu(menuProvId));
  }
}
function openModelMenu() {
  if (!state.providers.length) {
    toast('Add a provider first — opening Settings → Providers.', 'ok', 2400);
    openSettings('providers');
    return;
  }
  const menu = $('#model-menu');
  if (!menu.classList.contains('hidden')) { menu.classList.add('hidden'); return; }
  menuProvId = state.active.providerId || state.providers[0].id;
  $('#model-search').value = '';
  menu.classList.remove('hidden');
  renderModelMenu(menuProvId);
  if (menuProvId) ensureLoaded(menuProvId);
  $('#model-search').focus();
}

/* ── debug page ──────────────────────────────────────────── */
const KIND_CLASS = (k, e) => {
  if (e.error || (e.status && e.status >= 400)) return 'kind-err';
  if (k === 'chat' || k === 'chat-fallback' || k === 'model-test' || k === 'provider-test' || k === 'models') return 'kind-chat';
  if (k && k.startsWith('storage')) return 'kind-storage';
  if (k && k.startsWith('provider')) return 'kind-provider-add';
  if (k && k.startsWith('tool')) return 'kind-tool';
  return 'kind-local';
};
/* 1.6.7: four calm buckets instead of six overlapping ones.
   api    = anything that talked to a provider (chat, fallbacks, tests, model lists)
   tools  = tool calls (future tool runtime)
   config = everything local that changed state (providers, settings, prompts, storage) */
function logCategoryOf(e) {
  const k = String(e.kind || '').toLowerCase();
  if (k.startsWith('tool')) return 'tools';
  if (['chat', 'chat-fallback', 'model-test', 'provider-test', 'models'].includes(k)) return 'api';
  return 'config';
}
function logCategoryLabel(key) { return ({ api: 'API & models', tools: 'Tool calls', config: 'Config & storage' }[key] || 'Other'); }

export async function loadLogs() {
  try {
    const body = await api.getLogs(2000);
    const next = body.entries || [];
    logRev = Number(body.rev || 0);
    const sig = next.slice(0, 40).map(logId).join('||');
    logCache = next;
    // Precompute a lowercase search blob once per entry instead of
    // JSON.stringify-ing the whole cache on every filter keystroke.
    searchBlob = new Map(next.map((e) => [logId(e), JSON.stringify(e).toLowerCase()]));
    $('#dbg-info').textContent = body.database ? `${body.database} · ${logCache.length} entries · ${body.mode === 'detailed-encrypted' ? 'detailed encrypted' : 'simple'} · server ${serverVersion || ''}` : 'memory-only mode — logging disabled';
    if (sig !== logCacheSig || !document.querySelector('#dbg-list .dbg-entry')) {
      logCacheSig = sig;
      renderLogs();
    }
  } catch (e) { $('#dbg-info').textContent = 'logs unavailable: ' + e.message; }
}
function logId(e) { return e.id || `${e.ts || ''}|${e.kind || ''}|${e.providerId || ''}|${e.model || ''}|${e.status || ''}|${e.ms || ''}`; }
function renderLogDetail(root, e, id) {
  root.innerHTML = '';
  const blocks = [];
  if (e.detail?.request) blocks.push(['Request / prompt', e.detail.request]);
  if (e.detail?.response) blocks.push(['Response', e.detail.response]);
  if (e.detail?.error || e.detail?.upstream) blocks.push(['Error', { error: e.detail.error, upstream: e.detail.upstream }]);
  const base = { kind: e.kind, provider: e.provider, model: e.model, status: e.status, ms: e.ms, usage: e.usage, error: e.error, _encrypted: e._encrypted, chatId: e.chatId, traceId: e.traceId, systemPromptIncluded: e.systemPromptIncluded, systemPromptId: e.systemPromptId, systemPromptChars: e.systemPromptChars };
  blocks.unshift(['Event metadata', base]);
  for (const [label, val] of blocks) {
    const sec = document.createElement('section');
    sec.className = 'dbg-section';
    sec.innerHTML = `<div class="dbg-section-title">${esc(label)}<button class="icon-btn dbg-copy-block" type="button">copy</button></div>`;
    const pre = document.createElement('pre');
    pre.textContent = JSON.stringify(val, null, 2);
    sec.appendChild(pre);
    sec.querySelector('button').addEventListener('click', () => navigator.clipboard?.writeText(pre.textContent).then(() => toast('Copied.', 'ok', 1200)));
    root.appendChild(sec);
  }
  if (logDetailScroll.has(id)) root.scrollTop = logDetailScroll.get(id);
  root.addEventListener('scroll', () => logDetailScroll.set(id, root.scrollTop), { passive: true });
}
function renderOneLog(e) {
  const id = logId(e), open = expandedLogs.has(id);
  const wrap = document.createElement('article');
  wrap.className = 'dbg-entry' + (open ? ' expanded' : '');
  wrap.dataset.logId = id;
  const t = (e.ts || '').slice(11, 19) || (e.ts || '');
  const status = e.status != null ? String(e.status) : '';
  const statusCls = e.status === 499 ? 'abort' : e.status && e.status < 400 ? 'ok' : e.status ? 'bad' : 'abort';
  const usage = e.usage && (e.usage.total_tokens != null ? `${e.usage.total_tokens} tok` : '');
  const title = [e.provider, e.model].filter(Boolean).join(' / ') || (e.from || e.to || e.kind || 'event');
  const attempt = e.fallbackIndex > 0 ? ` <span class="dbg-fallback">fallback ${e.fallbackIndex + 1}</span>` : '';
  const fields = Array.isArray(e.fields) && e.fields.length ? ` <span class="dbg-fields">· ${esc(e.fields.join(', '))}</span>` : '';
  wrap.innerHTML = `<div class="dbg-row"><span class="dbg-time">${esc(t)}</span><span class="dbg-kind ${KIND_CLASS(e.kind, e)}">${esc(e.kind || 'event')}</span><span class="dbg-main">${esc(title)}${attempt}${fields}</span>${status ? `<span class="dbg-status ${statusCls}">${esc(status)}</span>` : ''}${e.ms != null ? `<span class="dbg-ms">${esc(String(e.ms))}ms</span>` : ''}${usage ? `<span class="dbg-tok">${esc(usage)}</span>` : ''}${e._encrypted ? '<span class="dbg-lock">encrypted</span>' : ''}<button class="btn dbg-open" type="button" data-log-open="1">${open ? 'Close' : 'Open'}</button></div><div class="dbg-detail ${open ? '' : 'hidden'}"></div>`;
  const detail = wrap.querySelector('.dbg-detail');
  renderLogDetail(detail, e, id);
  const toggle = () => {
    if (expandedLogs.has(id)) expandedLogs.delete(id);
    else expandedLogs.add(id);
    renderLogs();
  };
  wrap.querySelector('.dbg-open').addEventListener('click', (ev) => { ev.stopPropagation(); toggle(); });
  wrap.querySelector('.dbg-row').addEventListener('click', (ev) => { if (ev.target.closest('button')) return; toggle(); });
  return wrap;
}
function filteredLogRows() {
  const q = ($('#dbg-filter').value || '').toLowerCase();
  let rows = q ? logCache.filter((e) => (searchBlob.get(logId(e)) || '').includes(q)) : logCache;
  if (logCategory !== 'all') rows = rows.filter((e) => logCategoryOf(e) === logCategory);
  return rows.slice(0, logVisible);
}
function renderLogs() {
  const list = $('#dbg-list');
  const savedScroll = list.scrollTop;
  const wasNearBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 120;
  const rows = filteredLogRows();
  list.innerHTML = '';
  document.querySelectorAll('[data-log-category]').forEach((b) => b.classList.toggle('active', b.dataset.logCategory === logCategory));
  const groups = { api: [], tools: [], config: [] };
  rows.forEach((e) => (groups[logCategoryOf(e)] ||= []).push(e));
  if (!rows.length) { list.innerHTML = '<div class="dbg-empty">No matching log entries.</div>'; return; }
  const keys = logCategory === 'all' ? ['api', 'tools', 'config'] : [logCategory];
  for (const key of keys) {
    const group = groups[key] || [];
    if (!group.length) continue;
    const sec = document.createElement('section');
    sec.className = 'dbg-group';
    sec.innerHTML = `<div class="dbg-group-head"><span>${esc(logCategoryLabel(key))}</span><span>${group.length}</span></div><div class="dbg-group-list"></div>`;
    const box = sec.querySelector('.dbg-group-list');
    group.forEach((e) => box.appendChild(renderOneLog(e)));
    list.appendChild(sec);
  }
  requestAnimationFrame(() => {
    list.scrollTop = wasNearBottom ? list.scrollHeight : savedScroll;
    list.querySelectorAll('.dbg-entry.expanded').forEach((w) => {
      const id = w.dataset.logId;
      const d = w.querySelector('.dbg-detail');
      if (d && logDetailScroll.has(id)) d.scrollTop = logDetailScroll.get(id);
    });
  });
}
function startLogAutoRefresh() {
  if (logTimer) return;
  logTimer = setInterval(async () => {
    if (document.body.dataset.page !== 'debug' || !$('#dbg-auto').checked || document.hidden) return;
    // 1.7.0 optimization: probe the journal revision first (one indexed
    // aggregate query server-side). The full 2000-entry payload is fetched
    // only when something actually changed.
    try {
      const rev = await api.getLogsRev();
      if (Number(rev.rev || 0) === logRev) return;
    } catch { /* fall through to a full load */ }
    loadLogs();
  }, 4000);
}

/* ── storage migration ───────────────────────────────────── */
async function migrateTo(dir) {
  // 1.8.0 (issue 18): same-folder moves are answered before any confirmation
  const norm = (x) => String(x || '').replace(/[/\\]+$/, '');
  if (dir !== null && state.storage && !state.storage.memoryOnly && norm(dir) === norm(state.storage.dir)) {
    toast('That folder is already the current data area — nothing to move.', 'ok', 4500);
    return;
  }
  const target = dir === null ? 'memory-only (nothing persisted)' : dir;
  const ok = await confirmAction({
    title: 'Move data area?',
    message: `Move ALL stored data (providers+encrypted keys, chats, settings, logs) to:\n\n${target}\n\nThe current area is copied first, the copy is verified, then it becomes the default and the originals are deleted. The manifest stays at its fixed location.`,
    confirmText: 'Move data',
  });
  if (!ok) return;
  const btn = $('#sto-apply');
  btn.disabled = true;
  btn.textContent = 'Moving…';
  try {
    const body = await api.setStorage(dir);
    state.storage = body.storage;
    const r = body.report || {};
    renderSettingsStorage();
    renderStorageNotes();
    // 1.8.0 (issue 18): moving to the CURRENT area is a calm no-op, not an error
    if (r.switched === false && r.reason === 'same area') {
      toast('That folder is already the current data area — nothing to move.', 'ok', 5000);
      return;
    }
    const copied = Array.isArray(r.copied) ? r.copied : [];
    const removed = Array.isArray(r.removedOld) ? r.removedOld : [];
    toast(`Storage switched: ${copied.length} items copied & verified` + (removed.length ? `, ${removed.length} originals removed` : '') + ` → ${r.to || 'memory-only'}`, 'ok', 6000);
  } catch (e) {
    toast(`Migration aborted: ${e.message}`, 'err', 7000);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Move';
  }
}

/* ── settings persistence ─────────────────────────────────── */
let setTimer = null;
function saveSettings(patch) {
  Object.assign(state.settings, patch);
  clearTimeout(setTimer);
  setTimer = setTimeout(() => { api.setSettings(patch).catch(() => {}); }, 250);
  renderModelUI();
}

async function patchProviderModels(pid, next) {
  const before = state.providers.find((p) => p.id === pid);
  if (!before) return;
  const optimistic = { ...before, models: { ...(before.models || {}), ...next } };
  state.providers = state.providers.map((p) => p.id === pid ? optimistic : p);
  reconcileActiveSelection();
  renderSettingsModels();
  renderModelUI();
  if (!$('#model-menu').classList.contains('hidden')) renderModelMenu(menuProvId);
  try {
    const body = await api.patchProvider(pid, { models: next });
    state.providers = state.providers.map((p) => p.id === body.provider.id ? body.provider : p);
    renderSettingsModels();
    renderModelUI();
    if (!$('#model-menu').classList.contains('hidden')) renderModelMenu(menuProvId);
    return body.provider;
  } catch (err) {
    state.providers = state.providers.map((p) => p.id === pid ? before : p);
    renderSettingsModels();
    renderModelUI();
    if (!$('#model-menu').classList.contains('hidden')) renderModelMenu(menuProvId);
    toast(err.message, 'err');
    throw err;
  }
}

const ensureSettingsModelsLoaded = () => {
  const pid = settingsModelProviderId();
  if (pid && !state.providerModels[pid]) fetchModelsFor(pid, { silent: true }).then(renderSettingsModels).catch(() => renderSettingsModels());
};
const ensureAllProfileModelsLoaded = async () => { await Promise.allSettled(state.providers.map((p) => state.providerModels[p.id] ? Promise.resolve() : fetchModelsFor(p.id, { silent: true }))); };
const isFreeModel = (m) => /(^|[:/_-])free$/i.test(m.id || '') || (!!m.pricing && Number(m.pricing.prompt) === 0 && Number(m.pricing.completion) === 0);
const isFreeId = (id, list) => isFreeModel((list || []).find((m) => m.id === id) || { id });

/* ── wiring ────────────────────────────────────────────── */
export function bindAll() {
  // 1.7.1: the provider form's selects were only populated once the user
  // clicked New provider / Edit / Save — on a fresh visit they looked empty
  // and unchangeable. Initialise the editor (without stealing focus) at boot.
  setProviderEditorMode('');

  // sidebar toggle (unified; the settings/debug headers have their own on mobile)
  $('#side-toggle').addEventListener('click', () => toggleSidebar());
  document.querySelectorAll('.page-side-toggle').forEach((b) => b.addEventListener('click', () => toggleSidebar()));

  // click backdrop to close on mobile
  document.addEventListener('click', (e) => {
    if (window.innerWidth > 860) return;
    if (!document.body.classList.contains('side-open')) return;
    if (e.target.closest('#sidebar')) return;
    if (e.target.closest('#side-toggle')) return;
    if (e.target.closest('.page-side-toggle')) return; // 1.7.2: same click opens; don't close it again
    toggleSidebar(false);
  });

  $('#np-add').addEventListener('click', () => openSettings('providers'));
  $('#np-settings').addEventListener('click', () => openSettings('providers'));
  $('#prov-add').addEventListener('click', () => { resetProviderEditor(); $('#prov-form').scrollIntoView({ behavior: 'smooth', block: 'nearest' }); });
  $('#prov-cancel').addEventListener('click', () => resetProviderEditor(false));
  $('#prov-save').addEventListener('click', saveProviderInline);
  $('#prov-test').addEventListener('click', testProviderInline);
  $('#prov-show').addEventListener('click', () => { const k = $('#prov-key'); k.type = k.type === 'password' ? 'text' : 'password'; });
  $('#prov-url').addEventListener('input', () => { $('#prov-test').disabled = !$('#prov-edit-id').value && !$('#prov-url').value.trim(); });
  $('#prov-preset').addEventListener('change', (e) => applyProviderPreset(e.target.value));
  $('#prov-adapter').addEventListener('change', (e) => {
    const def = ADAPTER_DEFAULT_BASE[e.target.value];
    if (def && !$('#prov-url').value.trim()) { $('#prov-url').value = def; $('#prov-test').disabled = false; }
  });

  // confirm dialog
  $('#confirm-close').addEventListener('click', () => finishConfirm(false));
  $('#confirm-cancel').addEventListener('click', () => finishConfirm(false));
  $('#confirm-accept').addEventListener('click', () => finishConfirm(true));
  $('#personalization-save').addEventListener('click', () => finishPersonalization(true));
  $('#personalization-skip').addEventListener('click', () => finishPersonalization(false));
  $('#personalization-dialog').addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA') { e.preventDefault(); finishPersonalization(true); } });
  $('#confirm-dialog').addEventListener('click', (e) => { if (e.target === e.currentTarget) finishConfirm(false); });
  $('#model-import-close').addEventListener('click', () => closeModelImport(false));
  $('#model-import-cancel').addEventListener('click', () => closeModelImport(false));
  $('#model-import-add').addEventListener('click', addSelectedProviderModels);
  $('#model-import-test').addEventListener('click', () => runImportTests());
  $('#model-import-manual-add').addEventListener('click', () => {
    const input = $('#model-import-manual-input');
    if (!input) return;
    const id = (input.value || '').trim();
    if (!id) return;
    if (!modelImportItems.some((m) => m.id === id)) modelImportItems.push({ id, manual: true });
    input.value = '';
    const provider = providerById(modelImportProviderId);
    if (provider) renderModelImportDialog(provider, modelImportItems);
  });
  $('#model-import-manual-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); $('#model-import-manual-add').click(); } });
  $('#model-import-search').addEventListener('input', () => { const provider = providerById(modelImportProviderId); if (provider) renderModelImportDialog(provider, modelImportItems); });
  $('#model-import-select-all').addEventListener('click', () => { document.querySelectorAll('#model-import-list [data-import-model]').forEach((x) => { x.checked = true; }); });
  $('#model-import-none').addEventListener('click', () => { document.querySelectorAll('#model-import-list [data-import-model]').forEach((x) => { x.checked = false; }); });
  $('#model-import-dialog').addEventListener('click', (e) => { if (e.target === e.currentTarget) closeModelImport(false); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#confirm-dialog').classList.contains('hidden')) { e.stopPropagation(); finishConfirm(false); } if (e.key === 'Escape' && !$('#model-import-dialog').classList.contains('hidden')) { e.stopPropagation(); closeModelImport(false); } }, true);

  // pages router
  document.querySelectorAll('.page-nav-btn').forEach((b) => {
    b.addEventListener('click', () => {
      location.hash = '#/' + b.dataset.page;
      showPage(b.dataset.page);
      closeSidebarIfMobile();
    });
  });
  window.addEventListener('hashchange', route);
  document.querySelectorAll('.set-nav-btn').forEach((b) => {
    b.addEventListener('click', () => setSec(b.dataset.sec));
  });

  // sidebar: new chat / list / badge / theme / wipe
  $('#chat-mode').addEventListener('change', async event => {
    const chat = activeChat() || newChatRecord();
    const target = event.target.value;
    if (isStreaming(chat.id) || !canConvertMode(chat.modeId, target, state.modes.map(m => m.id))) { renderMessages(); return; }
    if (target !== chat.modeId && await confirmAction({ title: 'Convert this conversation?', message: 'This is permanent. This conversation cannot return to Simple Mode or switch to another mode.', confirmText: 'Convert', danger: false })) {
      chat.modeId = target; touchChat(chat);
    }
    renderMessages();
  });
  $('#new-chat').addEventListener('click', () => {
    // 1.7.0: like mainstream chat UIs, starting/switching chats while a
    // generation runs is allowed — the stream keeps writing to its own chat.
    for (const chat of state.chats.filter(c => c.ephemeral)) stop(chat.id);
    state.chats = state.chats.filter(c => !c.ephemeral);
    newChatRecord();
    showPage('chat');           // works from Settings/Debug too: straight home
    renderSidebar();
    renderMessages();
    renderSystemPromptUI();
    refreshStreamingUI();
    refreshChatDebugIfOpen();
    closeSidebarIfMobile();
    $('#input').focus();
  });
  $('#chat-list').addEventListener('click', (e) => {
    const item = e.target.closest('.chat-item');
    if (!item) return;
    const id = item.dataset.id;
    // 1.8.0: pin toggle
    const pin = e.target.closest('[data-chat-pin]');
    if (pin) {
      const c = state.chats.find((x) => x.id === id);
      if (c) { c.pinned = !c.pinned; touchChat(c); renderSidebar(); }
      return;
    }
    if (e.target.closest('.del')) {
      state.chats = state.chats.filter((x) => x.id !== id);
      if (state.activeId === id) state.activeId = state.chats[0] ? state.chats[0].id : null;
      touchChats();
      renderSidebar();
      renderMessages();
      refreshChatDebugIfOpen();
      return;
    }
    // 1.8.0: in select mode, clicking a row toggles selection instead of opening
    if (state.selectMode) {
      if (selectedChats.has(id)) selectedChats.delete(id); else selectedChats.add(id);
      renderSidebar();
      return;
    }
    for (const chat of state.chats.filter(c => c.ephemeral && c.id !== id)) stop(chat.id);
    state.chats = state.chats.filter(c => !c.ephemeral || c.id === id);
    state.tempMode = !!state.chats.find(c => c.id === id)?.ephemeral;
    state.activeId = id;
    touchChat(state.chats.find((x) => x.id === id));
    showPage('chat');           // clicking a chat opens it, from any page
    renderSidebar();
    renderMessages();
    renderSystemPromptUI();
    refreshStreamingUI();
    refreshChatDebugIfOpen();
    closeSidebarIfMobile();
  });
  $('#endpoint-badge').addEventListener('click', () => openSettings('providers'));
  $('#side-theme').addEventListener('click', () => {
    saveSettings({ theme: nextTheme(state.settings.theme) });
    applyTheme();
  });

  document.querySelectorAll('[data-theme-choice]').forEach((button) => button.addEventListener('click', () => {
    saveSettings({ theme: normalizeTheme(button.dataset.themeChoice) });
    applyTheme();
  }));

  // sidebar trash icon = full wipe (same flow as Danger zone "Wipe all")
  $('#side-wipe').addEventListener('click', async () => {
    const copy = WIPE_COPY.all;
    if (!(await confirmAction({ title: copy[0], message: copy[1], confirmText: copy[2] }))) return;
    try { await api.wipe('all'); location.reload(); } catch (e) { toast(e.message, 'err'); }
  });

  // model menu + profile menu
  $('#model-btn').addEventListener('click', (e) => { e.stopPropagation(); $('#profile-menu').classList.add('hidden'); $('#system-prompt-menu').classList.add('hidden'); openModelMenu(); });
  $('#profile-btn').addEventListener('click', (e) => {
    e.stopPropagation();
    if (!state.settings.advancedProfiles) return;
    $('#model-menu').classList.add('hidden');
    $('#system-prompt-menu').classList.add('hidden');
    const menu = $('#profile-menu');
    menu.classList.toggle('hidden');
    renderProfileMenu();
  });
  $('#profile-menu').addEventListener('click', (e) => e.stopPropagation());
  document.addEventListener('click', () => { $('#model-menu')?.classList.add('hidden'); $('#profile-menu')?.classList.add('hidden'); $('#system-prompt-menu')?.classList.add('hidden'); });
  $('#profile-list').addEventListener('click', async (e) => {
    // 1.7.1: the row's switch is an explicit enable/disable control; clicking
    // an enabled switch turns routing off, anything else on the row enables.
    const sw = e.target.closest('[data-profile-switch]');
    const opt = e.target.closest('[data-profile-id]');
    if (!opt) return;
    const rowId = opt.dataset.profileId || null;
    const id = sw ? (state.activeProfileId === sw.dataset.profileSwitch ? null : sw.dataset.profileSwitch) : rowId;
    recordChatDebug('other', id ? 'Profile selected' : 'Profile cleared', id ? { profileId: id } : null);
    if (sw && !id) { /* switch turned routing off */ }
    try {
      const body = await api.setActiveProfile(id);
      state.active = body.active;
      state.activeProfileId = body.activeProfileId || null;
      state.profiles = body.profiles || state.profiles;
      $('#profile-menu').classList.add('hidden');
      renderModelUI();
      renderMessages();
      renderSidebar();
      renderSettingsModels();
      toast(id ? `Profile: ${state.profiles.find((p) => p.id === state.activeProfileId)?.name || 'active'}` : 'No profile — direct model picking enabled.', 'ok', 1800);
    } catch (err) { toast(err.message, 'err'); }
  });
  $('#profile-clear')?.addEventListener('click', async () => {
    recordChatDebug('other', 'Profile cleared');
    try {
      const body = await api.setActiveProfile(null);
      state.active = body.active;
      state.activeProfileId = null;
      state.profiles = body.profiles || state.profiles;
      $('#profile-menu').classList.add('hidden');
      renderModelUI();
      renderMessages();
      renderSidebar();
      renderSettingsModels();
      toast('No profile — direct model picking enabled.', 'ok', 1800);
    } catch (err) { toast(err.message, 'err'); }
  });
  $('#model-search').addEventListener('input', () => renderModelMenu(menuProvId));
  $('#model-menu').addEventListener('click', (e) => e.stopPropagation());
  $('#mm-provs').addEventListener('mouseover', (e) => {
    const row = e.target.closest('.mm-prov');
    if (!row || row.dataset.prov === menuProvId) return;
    menuProvId = row.dataset.prov;
    renderModelMenu(menuProvId);
    ensureLoaded(menuProvId);
  });
  $('#mm-provs').addEventListener('click', async (e) => {
    const row = e.target.closest('.mm-prov');
    if (!row) return;
    const id = row.dataset.prov;
    menuProvId = id;
    if (state.active.providerId !== id) {
      state.active = await api.setActive({ providerId: id });
      state.activeProfileId = null;
      renderModelUI();
      renderSidebar();
    }
    ensureLoaded(id);
    renderModelMenu(id);
  });
  $('#model-list').addEventListener('click', async (e) => {
    const opt = e.target.closest('.model-opt[data-model]');
    if (!opt) return;
    // 1.6.6: with a profile active, requests are routed by priority — direct
    // picking stays disabled until the user chooses “No profile”.
    if (state.settings.advancedProfiles && activeProfile()) {
      toast(`Profile “${activeProfile().name}” is routing by priority — choose “No profile” to pick models directly.`, 'err');
      return;
    }
    const model = opt.dataset.model;
    const hadProfile = !!state.activeProfileId;
    state.active = await api.setActive({ providerId: menuProvId, model });
    state.activeProfileId = null;
    $('#model-menu').classList.add('hidden');
    renderModelUI();
    renderMessages();
    // Picking an explicit model leaves profile mode — say so instead of
    // silently detaching the chain the user had selected.
    toast(
      hadProfile
        ? `Direct model: ${model} — profile detached`
        : `Model: ${state.providers.find((p) => p.id === menuProvId)?.name || ''} / ${model}`,
      'ok', 2200
    );
  });
  $('#model-refresh').addEventListener('click', async () => {
    if (!menuProvId) return;
    try {
      const list = await fetchModelsFor(menuProvId, { force: true });
      renderModelMenu(menuProvId);
      toast(`Model list refreshed (${list.length} from provider).`, 'ok', 2400);
    } catch { /* toasted already */ }
  });
  document.addEventListener('click', () => { $('#model-menu').classList.add('hidden'); $('#profile-menu').classList.add('hidden'); });

  // system prompts
  $('#sp-list').addEventListener('click', (e) => { const row = e.target.closest('[data-sp-edit]'); if (!row) return; setSpEditing(row.dataset.spEdit); renderSystemPromptSettings(); });
  $('#set-system').addEventListener('input', () => { const p = state.settings.systemPrompts.find((x) => x.id === getSpEditing()); if (!p) return; p.content = $('#set-system').value; if (p.id === state.settings.defaultSystemPromptId) state.settings.system = p.content; saveSystemPromptSettings().catch(() => {}); renderSystemPromptUI(); });
  // 1.8.0 (issue 9): a new prompt asks for its name FIRST via the popup
  $('#set-system-prompt-new').addEventListener('click', async () => {
    const ans = await askName({ title: 'New system prompt', sub: 'Give the prompt a name first — you write its text right after.', showDesc: false, okText: 'Create prompt' });
    if (!ans || !ans.name) return;
    const id = 'sp-' + Math.random().toString(36).slice(2, 9);
    state.settings.systemPrompts.push({ id, name: ans.name, content: '' });
    setSpEditing(id);
    renderSystemPromptSettings();
    await saveSystemPromptSettings();
    renderSystemPromptUI();
    const ta = $('#set-system');
    ta.focus();
    toast(`“${ans.name}” created — write the prompt text and press Save.`, 'ok', 2200);
  });
  $('#set-system-prompt-save').addEventListener('click', async () => {
    const p = state.settings.systemPrompts.find((x) => x.id === getSpEditing());
    if (!p) return;
    p.name = $('#set-system-prompt-name').value.trim() || 'Untitled prompt';
    p.content = $('#set-system').value;
    if (p.id === state.settings.defaultSystemPromptId) state.settings.system = p.content;
    await saveSystemPromptSettings();
    renderSystemPromptSettings();
    renderSystemPromptUI();
    toast(`Saved “${p.name}”.`, 'ok', 1500);
  });
  $('#set-system-prompt-delete').addEventListener('click', async () => {
    const p = state.settings.systemPrompts.find((x) => x.id === getSpEditing());
    if (!p || p.id === state.settings.defaultSystemPromptId) return;
    if (!(await confirmAction({ title: 'Delete system prompt?', message: `Delete system prompt “${p.name}”? Chats that had it checked simply stop sending it.`, confirmText: 'Delete prompt' }))) return;
    state.settings.systemPrompts = state.settings.systemPrompts.filter((x) => x.id !== p.id);
    state.settings.system = state.settings.systemPrompts.find((x) => x.id === state.settings.defaultSystemPromptId)?.content || '';
    setSpEditing(state.settings.defaultSystemPromptId);
    await saveSystemPromptSettings();
    renderSystemPromptSettings();
    renderSystemPromptUI();
    toast('System prompt deleted.', 'ok', 1600);
  });
  $('#system-prompt-btn').addEventListener('click', (e) => { e.stopPropagation(); $('#model-menu').classList.add('hidden'); $('#profile-menu').classList.add('hidden'); const m = $('#system-prompt-menu'); m.classList.toggle('hidden'); renderSystemPromptUI(); });
  $('#system-prompt-menu').addEventListener('click', (e) => e.stopPropagation());

  // 1.6.6: per-chat send toggles — disabled prompts are simply not sent.
  $('#system-prompt-list').addEventListener('change', (e) => {
    const input = e.target.closest('[data-sp-toggle]');
    if (!input) return;
    const chat = activeChat();
    if (!chat) return;
    const id = input.dataset.spToggle;
    const primary = activeSystemPrompt(chat);
    let ids = Array.isArray(chat.enabledPromptIds) ? [...chat.enabledPromptIds] : (primary ? [primary.id] : []);
    if (input.checked) {
      if (!ids.includes(id)) ids.push(id);
    } else {
      // 1.6.7: anything can be unticked, including the default — all unticked
      // simply means "no system message", so no separate option is needed.
      ids = ids.filter((x) => x !== id);
    }
    chat.enabledPromptIds = ids;
    touchChat(chat);
    recordChatDebug('other', input.checked ? 'System prompt enabled for this chat' : 'System prompt disabled for this chat', { id });
    renderSystemPromptUI();
  });
  $('#system-prompt-manage').addEventListener('click', () => { $('#system-prompt-menu').classList.add('hidden'); openSettings('generation'); });
  // hot-switch method radios
  $('#sp-mode-stack').addEventListener('change', (e) => { if (e.target.checked) { saveSettings({ systemPromptMode: 'stack' }); renderSystemPromptUI(); toast('Stack mode: enabled prompts send as a system stack, updates tagged “update:”.', 'ok', 2200); } });
  $('#sp-mode-replace').addEventListener('change', (e) => { if (e.target.checked) { saveSettings({ systemPromptMode: 'replace' }); renderSystemPromptUI(); toast('Replace mode: only the selected prompt is sent.', 'ok', 2200); } });
  $('#prompt-vars-table').addEventListener('click', (e) => {
    const b = e.target.closest('[data-copy-var]');
    if (!b) return;
    navigator.clipboard?.writeText(b.dataset.copyVar).then(() => toast(`Copied ${b.dataset.copyVar}`, 'ok', 1200));
  });

  // general / personalization
  let generalTimer = null;
  const saveGeneralSettings = () => {
    clearTimeout(generalTimer);
    generalTimer = setTimeout(() => {
      const patch = { username: state.settings.username, age: state.settings.age, preferredName: state.settings.preferredName, agentName: state.settings.agentName || 'Archx Agent' };
      api.setSettings(patch).then((x) => { if (x?.settings) state.settings = { ...state.settings, ...x.settings }; renderModelUI(); renderSystemPromptUI(); }).catch(() => {});
    }, 250);
  };
  $('#set-username').addEventListener('input', (e) => { state.settings.username = e.target.value; saveGeneralSettings(); });
  $('#set-age').addEventListener('input', (e) => { state.settings.age = e.target.value; saveGeneralSettings(); });
  $('#set-preferred-name').addEventListener('input', (e) => { state.settings.preferredName = e.target.value; saveGeneralSettings(); });
  $('#set-agent-name').addEventListener('input', (e) => { state.settings.agentName = e.target.value || 'Archx Agent'; saveGeneralSettings(); renderModelUI(); });

  // generation
  $('#set-temp').addEventListener('input', (e) => { $('#temp-val').textContent = Number(e.target.value).toFixed(1); saveSettings({ temperature: Number(e.target.value) }); });
  $('#set-max').addEventListener('input', (e) => saveSettings({ maxTokens: e.target.value ? Number(e.target.value) : null }));
  $('#set-stream').addEventListener('change', (e) => saveSettings({ stream: e.target.checked }));
  $('#set-reasoning').addEventListener('change', (e) => { saveSettings({ reasoning: e.target.checked }); renderMessages(); });
  $('#set-advanced-profiles').addEventListener('change', (e) => {
    recordChatDebug('other', 'Advanced profiles toggled', { enabled: e.target.checked });
    saveSettings({ advancedProfiles: e.target.checked });
    renderModelUI();
    renderMessages();
    if (!e.target.checked) { api.setActiveProfile(null).then((body) => { state.active = body.active; state.activeProfileId = null; renderModelUI(); renderMessages(); }).catch(() => {}); }
  });
  $('#set-logs-simple').addEventListener('change', (e) => e.target.checked && (recordChatDebug('other', 'Settings changed', { logsMode: 'simple' }), saveSettings({ logsMode: 'simple' })));
  $('#set-logs-detailed').addEventListener('change', (e) => e.target.checked && (recordChatDebug('other', 'Settings changed', { logsMode: 'detailed-encrypted' }), saveSettings({ logsMode: 'detailed-encrypted' })));

  // providers
  $('#prov-list').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-prov-act]');
    if (!btn) return;
    const id = btn.dataset.id;
    if (btn.dataset.provAct === 'test') {
      try { btn.disabled = true; btn.textContent = 'Testing…'; const r = await api.testProvider(id); toast(`${providerById(id)?.name || 'Provider'} reachable · ${r.modelCount} models · ${r.ms} ms`, 'ok', 2600); }
      catch (e) { toast(e.message, 'err', 5000); }
      finally { btn.disabled = false; btn.textContent = 'Test'; }
      return;
    }
    if (btn.dataset.provAct === 'edit') editProviderInline(id);
    else if (btn.dataset.provAct === 'del') openProviderDeleteDialog(id);
  });

  // models
  $('#sec-models').addEventListener('change', (e) => {
    const input = e.target.closest('[data-model-select]');
    if (!input) return;
    const pid = settingsModelProviderId();
    toggleModelSelection(pid, input.dataset.id, input.checked);
    renderSettingsModels();
  });
  $('#mdl-delete-selected').addEventListener('click', async () => {
    const pid = settingsModelProviderId(), p = providerById(pid), ids = selectedModelsFor(pid);
    if (!p || !ids.length) return;
    if (!(await confirmAction({ title: 'Delete selected models?', message: `Delete ${ids.length} model${ids.length === 1 ? '' : 's'} from ${p.name}? Profile entries are kept paused so they can be restored if you add the models again later.`, confirmText: `Delete ${ids.length} model${ids.length === 1 ? '' : 's'}` }))) return;
    try {
      const body = await api.deleteProviderModels(pid, ids);
      state.providers = state.providers.map((x) => x.id === pid ? body.provider : x);
      state.profiles = body.profiles || state.profiles;
      state.active = body.active || state.active;
      clearModelSelection();
      renderSettingsModels(); renderProfileMenu(); renderModelUI();
      toast(`Deleted ${body.deleted.length} model${body.deleted.length === 1 ? '' : 's'}.`, 'ok', 2000);
    } catch (err) { toast(err.message, 'err'); }
  });
  $('#mdl-custom-add').addEventListener('click', async () => {
    const pid = settingsModelProviderId(), p = providerById(pid), input = $('#mdl-custom-input'), id = input.value.trim();
    if (!p || !id) return toast('Choose a provider and enter a model id.', 'err');
    const custom = new Set(p.models.custom || []);
    if (custom.has(id)) return toast('That custom model is already configured.', 'err');
    custom.add(id);
    try { await patchProviderModels(pid, { hidden: p.models.hidden || [], custom: [...custom], freeOnlyManualEnabled: p.freeOnlyManualEnabled || [], freeOnlyAutoHidden: p.freeOnlyAutoHidden || [] }); input.value = ''; toast(`Added custom model: ${id}`, 'ok', 1800); } catch (err) { toast(err.message, 'err'); }
  });
  $('#mdl-custom-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); $('#mdl-custom-add').click(); } });

  $('#mdl-free-only').addEventListener('change', async (e) => {
    const pid = settingsModelProviderId();
    const p = providerById(pid);
    if (!pid || !p) return;
    try {
      if (!state.providerModels[pid]) await fetchModelsFor(pid, { silent: true });
      const live = state.providerModels[pid] || [];
      if (e.target.checked) {
        const hidden = new Set(p.models.hidden || []), auto = new Set(p.freeOnlyAutoHidden || []), manual = new Set(p.freeOnlyManualEnabled || []);
        for (const m of live) if (!isFreeModel(m) && !manual.has(m.id)) { hidden.add(m.id); auto.add(m.id); }
        const body = await api.patchProvider(pid, { freeOnly: true, freeOnlyAutoHidden: [...auto], freeOnlyManualEnabled: [...manual], models: { catalog: p.models.catalog, catalogInitialized: p.models.catalogInitialized, selectionMode: p.models.selectionMode, hidden: [...hidden], custom: p.models.custom } });
        state.providers = state.providers.map((x) => x.id === body.provider.id ? body.provider : x);
      } else {
        const auto = new Set(p.freeOnlyAutoHidden || []), hidden = new Set(p.models.hidden || []);
        for (const id of auto) hidden.delete(id);
        const body = await api.patchProvider(pid, { freeOnly: false, freeOnlyAutoHidden: [], freeOnlyManualEnabled: p.freeOnlyManualEnabled || [], models: { catalog: p.models.catalog, catalogInitialized: p.models.catalogInitialized, selectionMode: p.models.selectionMode, hidden: [...hidden], custom: p.models.custom } });
        state.providers = state.providers.map((x) => x.id === body.provider.id ? body.provider : x);
      }
      renderSettingsModels();
      renderModelUI();
      renderModelMenu(menuProvId);
    } catch (err) { e.target.checked = !e.target.checked; toast(err.message, 'err'); }
  });

  $('#sec-models').addEventListener('click', async (e) => {
    const probe = e.target.closest('[data-model-probe]');
    if (probe) { openProbeDialog(settingsModelProviderId(), probe.dataset.id); return; }
    const del = e.target.closest('[data-model-delete]');
    if (del) {
      const pid = settingsModelProviderId(), p = providerById(pid), id = del.dataset.id;
      if (!p) return;
      const ok = await confirmAction({ title: 'Delete model from provider list?', message: `Delete “${id}” from ${p.name}? It will disappear from Enabled/Disabled and from direct Chat. A future Fetch models can discover it again. Any profile entry is kept paused so you can recover it by re-adding the model.`, confirmText: 'Delete model' });
      if (!ok) return;
      del.disabled = true;
      try {
        const body = await api.deleteProviderModel(pid, id);
        state.providers = state.providers.map((x) => x.id === body.provider.id ? body.provider : x);
        state.profiles = body.profiles || state.profiles;
        renderSettingsModels(); renderProfileMenu(); renderModelUI();
        toast(`Deleted ${id} from ${p.name}.`, 'ok', 2000);
      } catch (err) { toast(err.message, 'err'); del.disabled = false; }
      return;
    }
    const test = e.target.closest('[data-mdltst]');
    if (test) { const pid = settingsModelProviderId(), id = test.dataset.id; try { test.disabled = true; test.textContent = 'Testing…'; const r = await api.testModel(pid, id); toast(`${id}: ${r.reply || '(empty response)'} · ${r.ms} ms`, 'ok', 5000); } catch (err) { toast(`${id}: ${err.message}`, 'err', 6000); } finally { test.disabled = false; test.textContent = 'Test'; } return; }
    const toggle = e.target.closest('[data-model-toggle]');
    if (toggle) {
      const pid = settingsModelProviderId(), p = providerById(pid), id = toggle.dataset.id;
      if (!p) return;
      recordChatDebug('other', 'Model list changed', { providerId: pid, model: id });
      const hidden = new Set(p.models.hidden), manual = new Set(p.freeOnlyManualEnabled || []);
      const enable = toggle.textContent.trim() === 'Enable';
      if (enable) { hidden.delete(id); if (p.freeOnly && !isFreeId(id, state.providerModels[pid] || [])) manual.add(id); }
      else { hidden.add(id); manual.delete(id); }
      await patchProviderModels(pid, { hidden: [...hidden], custom: p.models.custom, freeOnlyManualEnabled: [...manual], freeOnlyAutoHidden: p.freeOnlyAutoHidden || [] });
      return;
    }
    const btn = e.target.closest('[data-mdl]');
    if (!btn) return;
    const pid = settingsModelProviderId(), p = providerById(pid);
    if (!p) return;
    const id = btn.dataset.id, act = btn.dataset.mdl;
    const hidden = new Set(p.models.hidden), custom = new Set(p.models.custom), manual = new Set(p.freeOnlyManualEnabled || []), auto = new Set(p.freeOnlyAutoHidden || []);
    if (act === 'show') { hidden.delete(id); auto.delete(id); if (p.freeOnly && !isFreeId(id, state.providerModels[pid] || [])) manual.add(id); }
    if (act === 'uncustom') { custom.delete(id); hidden.delete(id); auto.delete(id); manual.delete(id); }
    await patchProviderModels(pid, { hidden: [...hidden], custom: [...custom], freeOnlyAutoHidden: [...auto], freeOnlyManualEnabled: [...manual] });
  });

  // profiles
  $('#mdl-provider-sel').addEventListener('change', () => { clearModelSelection(); renderSettingsModels(); ensureSettingsModelsLoaded(); });
  $('#mdl-provider-tabs').addEventListener('click', (e) => { const btn = e.target.closest('[data-provider-id]'); if (!btn) return; clearModelSelection(); $('#mdl-provider-sel').value = btn.dataset.providerId; renderSettingsModels(); ensureSettingsModelsLoaded(); });
  $('#mdl-search').addEventListener('input', renderSettingsModels);
  $('#mdl-fetch').addEventListener('click', () => fetchModelsFromProvider({ interactive: true }));
  $('#mdl-test-all').addEventListener('click', async () => {
    const pid = settingsModelProviderId(), provider = providerById(pid);
    if (!provider) return toast('Choose a provider first.', 'err');
    if (!(provider.models.catalog || []).length) return toast('Fetch models and add at least one model first.', 'err');
    const btn = $('#mdl-test-all');
    btn.disabled = true; btn.textContent = 'Testing all…';
    try {
      const body = await api.testAllModels(pid);
      state.providers = state.providers.map((p) => p.id === body.provider.id ? body.provider : p);
      renderSettingsModels(); renderModelUI(); renderModelMenu(menuProvId);
      toast(`Tested ${body.count} model${body.count === 1 ? '' : 's'}: ${body.passed} working, ${body.failed} disabled.`, body.failed ? 'ok' : 'ok', 4200);
    } catch (err) { toast(err.message, 'err', 5000); }
    finally { btn.disabled = false; btn.textContent = 'Test all'; }
  });
  $('#mdl-profile-sel').addEventListener('change', async (e) => {
    try {
      const body = await api.setActiveProfile(e.target.value || null);
      state.active = body.active;
      state.activeProfileId = body.activeProfileId || null;
      state.profiles = body.profiles || state.profiles;
      setOpenProfile(state.activeProfileId);
      renderSettingsModels();
      renderModelUI();
      renderMessages();
      renderSidebar();
      await ensureAllProfileModelsLoaded();
      renderSettingsModels();
    } catch (err) { toast(err.message, 'err'); }
  });
  // 1.7.0: clicking a profile OPENs it in the editor without changing which
  // profile (if any) routes chat requests.
  $('#mdl-profile-list').addEventListener('click', (e) => { const btn = e.target.closest('[data-profile-id]'); if (!btn) return; setOpenProfile(btn.dataset.profileId); renderSettingsModels(); });
  $('#mdl-profile-provider-tabs').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-profile-provider-id]');
    if (!btn) return;
    setProfileAvailableProvider(btn.dataset.profileProviderId);
    $('#mdl-provider-sel').value = btn.dataset.profileProviderId;
    renderSettingsModels();
  });
  // 1.8.0 (issue 9): creating a profile asks for name + description + activate
  $('#mdl-profile-new').addEventListener('click', async () => {
    const ans = await askName({ title: 'New profile', sub: 'Name it, optionally describe it, and choose whether it should route chats right away.', showDesc: true, showEnable: true, enableLabel: 'Activate this profile now', okText: 'Create profile' });
    if (!ans || !ans.name) return;
    try {
      const body = await api.addModelProfile({ name: ans.name, description: ans.description, items: [] });
      state.profiles = body.profiles;
      state.activeProfileId = body.activeProfileId || null;
      if (ans.enable) {
        const b2 = await api.setActiveProfile(body.profile.id);
        state.active = b2.active; state.activeProfileId = b2.activeProfileId || body.profile.id; state.profiles = b2.profiles || state.profiles;
      }
      setOpenProfile(body.profile.id);
      renderSettingsModels(); renderModelUI(); renderMessages(); renderSidebar();
      await ensureAllProfileModelsLoaded();
      renderSettingsModels();
      toast(`Profile created: ${ans.name}. Add models from any provider below.`, 'ok', 2600);
    } catch (err) { toast(err.message, 'err'); }
  });
  $('#mdl-profile-rename').addEventListener('click', async () => {
    const p = editingProfile();
    if (!p) return;
    const ans = await askName({ title: 'Profile details', sub: 'Rename this profile or change its description.', initial: p.name, desc: p.description || '', okText: 'Save changes' });
    if (!ans || !ans.name) return;
    try {
      const body = await api.patchModelProfile(p.id, { name: ans.name, description: ans.description });
      state.profiles = body.profiles;
      renderSettingsModels(); renderProfileMenu(); renderModelUI();
      toast('Profile updated.', 'ok');
    } catch (err) { toast(err.message, 'err'); }
  });
  $('#mdl-profile-save').addEventListener('click', async () => {
    const p = editingProfile();
    if (!p) return;
    try { const body = await api.patchModelProfile(p.id, { items: p.items }); state.profiles = body.profiles; if (body.active) state.active = body.active; renderSettingsModels(); renderModelUI(); toast('Profile saved.', 'ok'); } catch (err) { toast(err.message, 'err'); }
  });
  $('#mdl-profile-delete').addEventListener('click', async () => {
    const p = editingProfile();
    if (!p) return;
    if (!(await confirmAction({ title: 'Delete profile?', message: `Delete profile ${p.name}?`, confirmText: 'Delete profile' }))) return;
    try { const body = await api.deleteModelProfile(p.id); state.profiles = body.profiles; state.activeProfileId = body.activeProfileId || null; setOpenProfile(null); renderSettingsModels(); renderModelUI(); toast('Profile deleted.', 'ok'); } catch (err) { toast(err.message, 'err'); }
  });
  $('#mdl-profile-add').addEventListener('click', async () => {
    const p = editingProfile();
    if (!p) return toast('Create or select a profile first.', 'err');
    const providerId = $('#mdl-profile-provider').value, model = $('#mdl-profile-model').value.trim(), priority = Math.max(1, Number($('#mdl-profile-priority').value) || 1);
    if (!providerId || !model) return toast('Choose a provider and enter a model id.', 'err');
    if (p.items.some((x) => x.providerId === providerId && x.model === model)) return toast('That model is already in the profile.', 'err');
    try { const items = [...p.items, { providerId, model, priority, order: p.items.length, enabled: true }]; const body = await api.patchModelProfile(p.id, { items }); state.profiles = body.profiles; if (body.active) state.active = body.active; $('#mdl-profile-model').value = ''; renderSettingsModels(); renderProfileMenu(); toast('Model added to profile.', 'ok', 1600); } catch (err) { toast(err.message, 'err'); }
  });
  $('#mdl-profile-available').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-profile-add-provider]');
    if (!btn) return;
    const p = editingProfile();
    if (!p) return;
    const providerId = btn.dataset.profileAddProvider, model = btn.dataset.profileAddModel;
    if (p.items.some((x) => x.providerId === providerId && x.model === model)) return;
    try { const items = [...p.items, { providerId, model, priority: 1, order: p.items.length, enabled: true }]; const body = await api.patchModelProfile(p.id, { items }); state.profiles = body.profiles; if (body.active) state.active = body.active; reconcileActiveSelection(); renderSettingsModels(); renderProfileMenu(); renderModelUI(); toast(`${model} added to ${p.name}.`, 'ok', 1500); } catch (err) { toast(err.message, 'err'); }
  });
  $('#mdl-profile-items').addEventListener('click', async (e) => {
    const p = editingProfile();
    if (!p) return;
    const toggle = e.target.closest('[data-profile-toggle-provider]');
    if (toggle) {
      const providerId = toggle.dataset.profileToggleProvider, model = toggle.dataset.profileToggleModel;
      const before = p.items;
      const next = before.map((x) => x.providerId === providerId && x.model === model ? { ...x, enabled: x.enabled === false } : x);
      state.profiles = state.profiles.map((x) => x.id === p.id ? { ...x, items: next } : x);
      reconcileActiveSelection();
      renderSettingsModels(); renderProfileMenu(); renderModelUI();
      try { const body = await api.patchModelProfile(p.id, { items: next }); state.profiles = body.profiles; if (body.active) state.active = body.active; reconcileActiveSelection(); renderSettingsModels(); renderProfileMenu(); renderModelUI(); }
      catch (err) { state.profiles = state.profiles.map((x) => x.id === p.id ? { ...x, items: before } : x); renderSettingsModels(); renderProfileMenu(); renderModelUI(); toast(err.message, 'err'); }
      return;
    }
    const btn = e.target.closest('[data-profile-remove-provider]');
    if (!btn) return;
    const providerId = btn.dataset.profileRemoveProvider, model = btn.dataset.profileRemoveModel;
    const items = p.items.filter((x) => !(x.providerId === providerId && x.model === model));
    if (!items.length) return toast('A profile must keep at least one model.', 'err');
    try { const body = await api.patchModelProfile(p.id, { items }); state.profiles = body.profiles; if (body.active) state.active = body.active; renderSettingsModels(); renderProfileMenu(); renderModelUI(); } catch (err) { toast(err.message, 'err'); }
  });
  $('#mdl-profile-items').addEventListener('change', async (e) => {
    const inp = e.target.closest('[data-profile-priority-provider]');
    if (!inp) return;
    const p = editingProfile();
    if (!p) return;
    const providerId = inp.dataset.profilePriorityProvider, model = inp.dataset.profilePriorityModel, priority = Math.max(1, Number(inp.value) || 1);
    const items = p.items.map((x) => x.providerId === providerId && x.model === model ? { ...x, priority } : x);
    try { const body = await api.patchModelProfile(p.id, { items }); state.profiles = body.profiles; if (body.active) state.active = body.active; reconcileActiveSelection(); renderSettingsModels(); renderProfileMenu(); renderModelUI(); } catch (err) { toast(err.message, 'err'); }
  });

  // storage
  $('#sto-apply').addEventListener('click', () => { const v = $('#sto-input').value.trim(); if (!v) return toast('Type a path first, or use one of the quick options.', 'err'); migrateTo(v); });
  $('#sto-default').addEventListener('click', () => migrateTo(state.storage.suggestions.default));
  $('#sto-local').addEventListener('click', () => migrateTo(state.storage.suggestions.local));
  $('#sto-memory').addEventListener('click', () => migrateTo(null));

  // 1.8.0: provider delete policy dialog (issue 5)
  $('#pd-close').addEventListener('click', () => { $('#provider-delete-dialog').classList.add('hidden'); pendingProviderDelete = null; });
  $('#pd-cancel').addEventListener('click', () => { $('#provider-delete-dialog').classList.add('hidden'); pendingProviderDelete = null; });
  $('#pd-pause').addEventListener('click', () => finishProviderDelete('pause'));
  $('#pd-remove').addEventListener('click', () => finishProviderDelete('remove'));

  // 1.8.0: generic name/details dialog (issue 9)
  $('#name-dialog-close').addEventListener('click', () => finishNameDialog(null));
  $('#name-dialog-cancel').addEventListener('click', () => finishNameDialog(null));
  $('#name-dialog-ok').addEventListener('click', () => finishNameDialog({ name: $('#name-dialog-name').value.trim(), description: $('#name-dialog-desc').value.trim(), enable: $('#name-dialog-enable').checked }));
  $('#name-dialog-name').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); $('#name-dialog-ok').click(); } });

  // 1.8.0: sidebar — temp mode, multi-select, pins (issues 3 & 4)
  $('#temp-mode').addEventListener('click', () => {
    for (const chat of state.chats.filter(c => c.ephemeral)) stop(chat.id);
    state.chats = state.chats.filter(c => !c.ephemeral);
    state.tempMode = !state.tempMode;
    newChatRecord(); renderSidebar(); renderMessages(); refreshStreamingUI();
    toast(state.tempMode ? 'Temporary chat — not saved or logged. Leaving this chat discards it.' : 'Back to saved chats.', 'ok', 3200);
  });
  $('#select-mode').addEventListener('click', () => { state.selectMode = !state.selectMode; if (!state.selectMode) selectedChats.clear(); renderSidebar(); });
  $('#select-all-chats').addEventListener('click', () => { state.chats.forEach((c) => selectedChats.add(c.id)); renderSidebar(); });
  $('#select-cancel').addEventListener('click', () => { state.selectMode = false; selectedChats.clear(); renderSidebar(); });
  $('#delete-selected-chats').addEventListener('click', async () => {
    const n = selectedChats.size;
    if (!n) return;
    if (!(await confirmAction({ title: 'Delete selected chats?', message: `Delete ${n} chat${n === 1 ? '' : 's'} permanently?`, confirmText: `Delete ${n}` }))) return;
    state.chats = state.chats.filter((c) => !selectedChats.has(c.id));
    if (selectedChats.has(state.activeId)) state.activeId = state.chats[0] ? state.chats[0].id : null;
    selectedChats.clear();
    state.selectMode = false;
    touchChats();
    renderSidebar(); renderMessages(); renderSystemPromptUI(); refreshStreamingUI(); refreshChatDebugIfOpen();
    toast(`Deleted ${n} chat${n === 1 ? '' : 's'}.`, 'ok');
  });

  // 1.8.0: web search tool toggle (issue 11)
  $('#btn-web').addEventListener('click', () => {
    state.webSearchOn = !state.webSearchOn;
    const b = $('#btn-web');
    b.classList.toggle('on', state.webSearchOn);
    b.setAttribute('aria-pressed', String(state.webSearchOn));
    toast(state.webSearchOn ? 'Web search ON — sends are grounded with keyless web search.' : 'Web search OFF.', 'ok', 2200);
  });

  // 1.8.0: studio (issue 2)
  document.querySelectorAll('.studio-tab').forEach((t) => t.addEventListener('click', () => {
    document.querySelectorAll('.studio-tab').forEach((x) => x.classList.toggle('active', x === t));
    ['image', 'tts', 'stt', 'vision'].forEach((k) => $('#studio-' + k).classList.toggle('hidden', k !== t.dataset.studioTab));
  }));
  $('#si-run').addEventListener('click', () => { studioImageRun().catch((e) => toast(e.message, 'err')); });
  $('#st-run').addEventListener('click', () => { studioTtsRun().catch((e) => toast(e.message, 'err')); });
  $('#sr-run').addEventListener('click', () => { studioSttRun().catch((e) => toast(e.message, 'err')); });
  $('#sv-run').addEventListener('click', () => { studioVisionRun().catch((e) => toast(e.message, 'err')); });

  // 1.8.0: memory page (issue 13)
  bindLibrary(confirmAction);
  $('#mem-refresh').addEventListener('click', loadMemoryStats);
  $('#mem-grid').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-mem-wipe]');
    if (!btn) return;
    const scope = btn.dataset.memWipe;
    const titles = { 'media-images': 'Wipe image assets?', 'media-videos': 'Wipe video assets?', 'media-docs': 'Wipe document assets?', chats: 'Wipe all chats?', logs: 'Clear all request logs?' };
    if (!(await confirmAction({ title: titles[scope] || 'Wipe?', message: 'This cannot be undone.', confirmText: 'Wipe' }))) return;
    try {
      if (scope === 'logs') await api.clearLogs();
      else await api.wipe(scope);
      if (scope === 'chats') { await loadState(); renderSidebar(); renderMessages(); }
      loadMemoryStats();
      toast('Done.', 'ok');
    } catch (err) { toast(err.message, 'err'); }
  });

  // 1.8.0: probe dialog (issue 7)
  $('#probe-close').addEventListener('click', () => $('#probe-dialog').classList.add('hidden'));
  $('#probe-save').addEventListener('click', saveProbe);
  $('#probe-run').addEventListener('click', runProbeNow);
  $('#probe-reset').addEventListener('click', () => { $('#probe-body').value = ''; toast('Custom body cleared — Save restores the default test document.', 'ok', 2600); });

  // 1.8.0: import dialog live-run controls (issues 1 & 8)
  $('#model-import-only-working').addEventListener('change', (e) => { if (e.target.checked) runImportTests(); });
  $('#mip-stop').addEventListener('click', () => { if (importRun) { importRun.stop = true; updateImportProgress(); } });
  $('#model-import-select-matching').addEventListener('click', () => {
    const q = ($('#model-import-search').value || '').trim().toLowerCase();
    document.querySelectorAll('#model-import-list [data-import-model]').forEach((x) => { x.checked = !q || x.dataset.importModel.toLowerCase().includes(q); });
  });

  // 1.8.0: tools settings (issue 11) + retention (issue 12)
  $('#set-search-enabled').addEventListener('change', (e) => saveSearchSettings({ enabled: e.target.checked }));
  $('#set-search-max').addEventListener('change', (e) => saveSearchSettings({ maxResults: Math.min(10, Math.max(1, Number(e.target.value) || 5)) }));
  $('#search-engine-list').addEventListener('click', (e) => {
    const up = e.target.closest('[data-eng-up]');
    const down = e.target.closest('[data-eng-down]');
    const engines = [...((state.settings.search || {}).engines || [])];
    const i = up ? Number(up.dataset.engUp) : down ? Number(down.dataset.engDown) : -1;
    if (i < 0) return;
    const j = up ? i - 1 : i + 1;
    if (j < 0 || j >= engines.length) return;
    [engines[i], engines[j]] = [engines[j], engines[i]];
    saveSearchSettings({ engines });
  });
  $('#search-test').addEventListener('click', async () => {
    $('#search-test-out').textContent = 'Testing…';
    try {
      const r = await api.webSearchTest();
      $('#search-test-out').textContent = r.engines.map((x) => `${x.engine}: ${x.ok ? `OK · ${x.count} results · ${x.ms} ms` : 'FAIL · ' + (x.error || '')}`).join('\n');
    } catch (e) { $('#search-test-out').textContent = e.message; }
  });
  ['ret-api', 'ret-tools', 'ret-config', 'ret-all'].forEach((id) => $('#' + id).addEventListener('change', saveRetention));

  // chat debug popover
  $('#chat-debug-btn').addEventListener('click', (e) => { e.stopPropagation(); toggleChatDebug(); });
  $('#chat-debug-close').addEventListener('click', () => toggleChatDebug(false));
  $('#chat-debug-refresh').addEventListener('click', () => loadChatDebug());
  $('#chat-debug-provider').addEventListener('change', renderChatDebug);
  document.querySelectorAll('[data-debug-tab]').forEach((btn) => btn.addEventListener('click', () => { chatDebugTab = btn.dataset.debugTab; document.querySelectorAll('[data-debug-tab]').forEach((x) => x.classList.toggle('active', x === btn)); renderChatDebug(); }));

  // debug page
  $('#dbg-refresh').addEventListener('click', () => { logVisible = 2000; loadLogs(); });
  $('#dbg-filter').addEventListener('input', () => { logVisible = 2000; renderLogs(); });
  document.querySelectorAll('[data-log-category]').forEach((b) => b.addEventListener('click', () => { logCategory = b.dataset.logCategory; logVisible = 2000; renderLogs(); }));
  $('#dbg-clear').addEventListener('click', async () => {
    if (!(await confirmAction({ title: 'Clear all logs?', message: 'Delete every request log file from the current data area?', confirmText: 'Clear logs' }))) return;
    await api.clearLogs();
    loadLogs();
    toast('Logs cleared.', 'ok');
  });
  startLogAutoRefresh();
  startChatDebugAutoRefresh();

  // chips
  CHIPS.forEach((c) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip';
    b.textContent = c;
    b.addEventListener('click', () => { $('#input').value = c; $('#input').focus(); });
    $('#chips').appendChild(b);
  });

  // branches (1.7.2)
  $('#branch-btn').addEventListener('click', (e) => {
    e.stopPropagation();
    const menu = $('#branch-menu');
    renderBranchUI();
    menu.classList.toggle('hidden');
  });
  $('#branch-menu').addEventListener('click', (e) => {
    e.stopPropagation();
    const open = e.target.closest('[data-branch-open]');
    if (!open) return;
    const chat = activeChat();
    if (!chat) return;
    if (switchBranch(chat, open.dataset.branchOpen)) {
      $('#branch-menu').classList.add('hidden');
      renderMessages();
      renderSidebar();
      toast('Switched to the selected continuation.', 'ok', 2000);
    } else {
      toast('Stop the current generation before switching branches.', 'err');
    }
  });

  // scoped wipes (1.7.2)
  const WIPE_COPY = {
    all: ['Wipe all stored data?', 'This permanently deletes providers, encrypted keys, models, profiles, settings, chats, logs and assets from the current data area.', 'Wipe everything'],
    'keep-providers': ['Wipe chat data but keep providers & personalization?', 'Conversations, request logs and memories are deleted. Providers, encrypted keys, model lists, profiles, your personalization (name, agent name…) and all settings stay exactly as they are.', 'Wipe chat data'],
    chats: ['Wipe all chats?', 'Every conversation and message disappears. Providers, keys, settings and generated artifacts remain.', 'Wipe chats'],
    'media-images': ['Wipe image assets?', 'All stored image files and their asset records are deleted.', 'Wipe images'],
    'media-videos': ['Wipe video assets?', 'All stored video files and their asset records are deleted.', 'Wipe videos'],
    'media-docs': ['Wipe document assets?', 'All stored documents/audio and their asset records are deleted.', 'Wipe documents'],
    library: ['Wipe the whole library?', 'Every asset record of every kind plus all files in the media folder are deleted.', 'Wipe library'],
  };
  document.querySelectorAll('[data-wipe-scope]').forEach((btn) => btn.addEventListener('click', async () => {
    const scope = btn.dataset.wipeScope;
    const copy = WIPE_COPY[scope] || WIPE_COPY.all;
    if (!(await confirmAction({ title: copy[0], message: copy[1], confirmText: copy[2] }))) return;
    try {
      await api.wipe(scope);
      if (scope === 'all' || scope === 'keep-providers') { location.reload(); return; }
      await loadState();
      renderSidebar(); renderMessages(); renderSettingsModels(); renderSettingsStorage(); renderBranchUI();
      toast(`Wiped: ${scope.replace(/-/g, ' ')}.`, 'ok');
    } catch (e) { toast(e.message, 'err'); }
  }));

  // global keys
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (isStreaming()) stop();
      else {
        if (!$('#personalization-dialog')?.classList.contains('hidden')) { finishPersonalization(false); return; }
        $('#model-menu').classList.add('hidden');
        $('#profile-menu').classList.add('hidden');
        $('#system-prompt-menu').classList.add('hidden');
        // 1.7.2: the provider editor is a permanent inline surface, not a
        // popup — Escape must not make it disappear (it looked "broken").
        if (chatDebugOpen) toggleChatDebug(false);
        if (window.innerWidth <= 860 && document.body.classList.contains('side-open')) toggleSidebar(false);
      }
    }
  });

  window.addEventListener('resize', () => {
    if (window.innerWidth > 860) document.body.classList.remove('side-open');
    updateLayoutVars();
  });

  bindComposer();
  bindMessageActions();
}

/* ── boot ────────────────────────────────────────── */
export async function boot() {
  bindAll();
  /* 1.9.0: custom dropdowns + file picks over the native controls */
  ['#si-model', '#st-model', '#sr-model', '#sv-model', '#prov-preset', '#prov-adapter', '#mdl-profile-provider', '#chat-debug-provider'].forEach((q) => attachDropdown($(q)));
  attachFilePick($('#si-ref'));
  attachFilePick($('#sr-file'));
  attachFilePick($('#sv-file'), { thumbs: true });
  try { await loadState(); }
  catch (e) { toast(`Could not reach the local server: ${e.message}`, 'err', 8000); }
  try {
    const h = await (await fetch('/api/health')).json();
    serverVersion = 'v' + h.version;
    $('#app-version').textContent = serverVersion;
  } catch { /* ignore */ }
  applyTheme();
  // re-init the provider editor now that adapters are known (bindAll ran
  // before loadState, when only the built-in adapter was listed)
  setProviderEditorMode($('#prov-edit-id').value || '');
  $('#app').classList.remove('hidden');
  renderSidebar();
  renderMessages();
  renderModelUI();
  if (!markdownReady()) toast('markdown-it failed to load — using the built-in renderer.', '', 3000);
  /* 1.9.0: async model loads land after first paint — refill pickers live */
  window.addEventListener('archx:models-loaded', () => { renderStudio(); });
  const first = state.active.providerId || (state.providers[0] && state.providers[0].id);
  if (first) fetchModelsFor(first, { silent: true }).catch(() => {});
  route();
  await showPersonalizationOnboarding();
}