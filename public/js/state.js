import { findDraft, isPersistentChat } from './chat-lifecycle.mjs';
/* Archx Agent — shared state + persistence calls (v3: global multi-provider profiles) */

import * as api from './api.js';
import { createChatWriter } from './chat-persistence.mjs';
import { toast } from './dom.js';
import { normalizeTheme } from './theme.mjs';
import { capsFor } from './capabilities.mjs';

export const state = {
  storage: null,
  providers: [],
  active: { providerId: null, model: null },
  profiles: [], // [{id,name,items:[{providerId,model,priority,order}]}]
  activeProfileId: null,
  settings: { system: '', systemPrompts: [], defaultSystemPromptId: null, defaultSystemPromptInitialized: true, temperature: 0.7, maxTokens: null, stream: true, theme: 'dark', reasoning: true, logsMode: 'simple', advancedProfiles: true, username: '', age: '', preferredName: '', agentName: 'Archx Agent' },
  chats: [],
  activeId: null,
  tempMode: false, // 1.8.0: while on, new chats are temporary (never persisted)
  selectMode: false, // 1.8.0: multi-select chats in the sidebar
  webSearchOn: false, // 1.8.0: composer Web tool toggle (session)
  providerModels: {},
  providerAdapters: ['openai-compatible'],
  modes: [{ id: 'simple-chat', name: 'Simple chat', description: 'Plain text conversation with the selected model. No tools.', capabilities: { tools: false, textInput: true, textOutput: true } }],
};

function normalizeSystemPrompts(settings = {}) {
  const source = Array.isArray(settings.systemPrompts) ? settings.systemPrompts : [];
  const prompts = source.filter((p) => p && typeof p.content === 'string').map((p, i) => ({
    id: typeof p.id === 'string' && p.id.trim() ? p.id : `sp-${i + 1}`,
    name: typeof p.name === 'string' && p.name.trim() ? p.name.trim() : `Prompt ${i + 1}`,
    content: p.content,
  }));
  const legacy = typeof settings.system === 'string' ? settings.system : '';
  if (!prompts.length) prompts.push({ id: 'sp-default', name: 'Default', content: legacy });
  else if (legacy.trim() && !prompts.some((p) => p.content === legacy)) prompts.unshift({ id: 'sp-legacy', name: 'Imported default', content: legacy });
  const wanted = typeof settings.defaultSystemPromptId === 'string' ? settings.defaultSystemPromptId : null;
  return { prompts, defaultId: prompts.some((p) => p.id === wanted) ? wanted : (prompts[0]?.id || null) };
}

function normalizeProfile(profile, index = 0) {
  const items = Array.isArray(profile?.items)
    ? profile.items
        .filter((x) => x && typeof x.providerId === 'string' && typeof x.model === 'string' && x.model.trim())
        .map((x, i) => ({ providerId: x.providerId, model: x.model.trim(), priority: Number(x.priority) > 0 ? Number(x.priority) : 1, order: Number.isFinite(Number(x.order)) ? Number(x.order) : i, enabled: x.enabled !== false }))
    : Array.isArray(profile?.models) && profile?.providerId
      ? profile.models.map((model, i) => ({ providerId: profile.providerId, model: String(model), priority: 1, order: i, enabled: true }))
      : [];
  return { id: profile.id || `mp-${index}`, name: profile.name || 'Profile', items };
}

export function normalizeProfiles(list) {
  return (Array.isArray(list) ? list : []).map(normalizeProfile);
}

export async function loadState() {
  const s = await api.getState();
  state.storage = s.storage;
  state.providers = s.providers;
  state.providerAdapters = Array.isArray(s.providerAdapters) && s.providerAdapters.length ? s.providerAdapters : ['openai-compatible'];
  state.modes = Array.isArray(s.modes) && s.modes.length ? s.modes : state.modes;
  state.active = s.active || { providerId: null, model: null };
  state.profiles = normalizeProfiles(s.profiles);
  state.activeProfileId = s.activeProfileId || null;
  const rawSettings = { reasoning: true, advancedProfiles: true, username: '', age: '', preferredName: '', agentName: 'Archx Agent', personalizationOnboarded: false, system: '', defaultSystemPromptInitialized: true, ...s.settings };
  const promptState = normalizeSystemPrompts(rawSettings);
  state.settings = { ...rawSettings, theme: normalizeTheme(rawSettings.theme), systemPrompts: promptState.prompts, defaultSystemPromptId: promptState.defaultId, system: promptState.prompts.find((p) => p.id === promptState.defaultId)?.content || rawSettings.system || '' };
  state.chats = (s.chats || []).map((c) => ({
    ...c,
    modeId: c.modeId || 'simple-chat',
    systemPromptId: c.systemPromptId !== undefined ? c.systemPromptId : state.settings.defaultSystemPromptId,
    debugTraceIds: Array.isArray(c.debugTraceIds) ? c.debugTraceIds : [],
    debugEvents: Array.isArray(c.debugEvents) ? c.debugEvents : [],
    branches: Array.isArray(c.branches) ? c.branches : [],
    // 1.7.0: a message can never be "still generating" after a reload — the
    // stream that owned it is gone. Persisted pending flags used to leave a
    // blinking caret on old messages forever.
    messages: (c.messages || []).map((m) => (m && m.pending ? { ...m, pending: false } : m)),
  }));
  state.activeId = s.activeId || null;
}

/* Read-only debug handle for support/tests (never used by app logic). */
if (typeof window !== 'undefined') window.__archxState = state;

export const activeProvider = () => state.providers.find((p) => p.id === state.active.providerId) || null;
export const providerById = (id) => state.providers.find((p) => p.id === id) || null;
export const activeProfile = () => state.profiles.find((p) => p.id === state.activeProfileId) || null;
export const profileItemsForProvider = (profile, providerId) => (profile?.items || []).filter((x) => x.providerId === providerId);
export const profileItem = (profile, providerId, model) => (profile?.items || []).find((x) => x.providerId === providerId && x.model === model) || null;
export const profileItemList = (profile, providerId) => (profile?.items || []).filter((x) => x.providerId === providerId);

/* Backwards-compatible helper for UI code that asks about a provider. */
export function activeProfileFor(p) {
  const profile = activeProfile();
  return profile && p && profile.items.some((x) => x.providerId === p.id) ? profile : null;
}

export function sortedProfileItems(profile) {
  return [...(profile?.items || [])].sort((a, b) => (Number(a.priority) || 1) - (Number(b.priority) || 1) || (Number(a.order) || 0) - (Number(b.order) || 0));
}

export function isFree(m) {
  if (/(^|[:/_-])free$/i.test(m.id || '')) return true;
  const pr = m.pricing;
  return !!(pr && Number(pr.prompt) === 0 && Number(pr.completion) === 0);
}

export function freeCount(p) {
  return (state.providerModels[p.id] || []).filter(isFree).length;
}

/* Curated visible models of one provider. When an active profile is selected,
   that profile only filters the active provider to its own member models. */
export function providerModelConfigured(p, modelId) {
  if (!p || !modelId) return false;
  const models = p.models || {};
  const catalog = Array.isArray(models.catalog) ? models.catalog : [];
  const custom = new Set(models.custom || []);
  if (models.selectionMode === 'checklist' && !catalog.includes(modelId) && !custom.has(modelId)) return false;
  if (models.selectionMode !== 'checklist' && models.catalogInitialized && !catalog.includes(modelId) && !custom.has(modelId)) return false;
  return true;
}

export function providerModelGloballyEnabled(p, modelId, liveList = null) {
  if (!providerModelConfigured(p, modelId)) return false;
  const models = p.models || {};
  if ((models.hidden || []).includes(modelId)) return false;
  if (p.freeOnly) {
    const manual = (p.freeOnlyManualEnabled || []).includes(modelId);
    if (manual) return true;
    const live = (liveList || state.providerModels[p.id] || []).find((m) => m.id === modelId);
    return isFree(live || { id: modelId });
  }
  return true;
}

/* Curated visible models of one provider. Provider catalog membership is now
   explicit: fetched-but-unchecked models never enter this picker. A profile
   can further filter the catalog, but global disable always wins. */
export function visibleModelsFor(p) {
  if (!p) return [];
  const raw = state.providerModels[p.id] || [];
  const custom = new Set(p.models.custom || []);
  const configured = new Set(p.models.catalog || []);
  const hidden = new Set(p.models.hidden || []);
  const profile = state.settings.advancedProfiles ? activeProfile() : null;
  const profileItems = profile ? profileItemList(profile, p.id) : null;
  const profileIds = profileItems ? new Set(profileItems.map((x) => x.model)) : null;
  const profileEnabled = profileItems ? new Set(profileItems.filter((x) => x.enabled !== false).map((x) => x.model)) : null;

  // 1.7.3: an active profile no longer HIDES models (a profile without any
  // Gemini models used to empty the whole Gemini picker). The full curated
  // catalog stays visible; the picker renders it locked/dimmed while a
  // profile routes, and profile membership is surfaced as a tag instead.
  let list = raw.filter((m) => {
    const legacyUninitialized = p.models.selectionMode !== 'checklist' && !p.models.catalogInitialized;
    const configuredHere = configured.has(m.id) || custom.has(m.id) || legacyUninitialized;
    if (!configuredHere) return false;
    if (hidden.has(m.id)) return false;
    if (p.freeOnly && !providerModelGloballyEnabled(p, m.id, raw)) return false;
    return true;
  });

  if (!raw.length) {
    list = [];
  }

  for (const id of custom) {
    if (list.some((m) => m.id === id)) continue;
    if (hidden.has(id)) continue;
    if (profileIds && !profileIds.has(id)) continue;
    if (profileEnabled && !profileEnabled.has(id)) continue;
    list.push({ id, owned_by: 'custom', custom: true, profile: !!profileIds });
  }
  if (profileItems) {
    for (const item of profileItems) {
      const id = item.model;
      if (item.enabled === false || hidden.has(id) || !providerModelConfigured(p, id)) continue;
      if (list.some((m) => m.id === id)) continue;
      list.unshift({ id, owned_by: 'profile', custom: custom.has(id), profile: true });
    }
  }
  return list.map((m) => ({ ...m, custom: custom.has(m.id) || !!m.custom, profile: !!profileIds }));
}

export const visibleModels = () => visibleModelsFor(activeProvider());

/* 1.8.0 (issue 2): every surface lists only models whose capabilities match.
   Overrides stored per provider win over the id heuristic. */
export const modelCaps = (providerId, modelId) => {
  const p = providerById(providerId);
  return capsFor(modelId, p?.models?.capabilities?.[modelId]);
};
export function studioModelsFor(kind) {
  const out = [];
  for (const p of state.providers) {
    for (const m of visibleModelsFor(p)) {
      if (modelCaps(p.id, m.id)[kind]) out.push({ providerId: p.id, providerName: p.name, model: m.id });
    }
  }
  return out;
}
export function reconcileActiveSelection() {
  const profile = state.settings.advancedProfiles ? activeProfile() : null;
  if (profile) {
    const next = sortedProfileItems(profile).find((item) => {
      const p = providerById(item.providerId);
      return item.enabled !== false && providerModelGloballyEnabled(p, item.model, state.providerModels[item.providerId] || []);
    });
    state.active = next ? { providerId: next.providerId, model: next.model } : { providerId: state.active.providerId, model: null };
    return state.active;
  }
  if (state.active.providerId && state.active.model) {
    const p = providerById(state.active.providerId);
    if (!providerModelGloballyEnabled(p, state.active.model, state.providerModels[state.active.providerId] || [])) state.active = { ...state.active, model: null };
  }
  return state.active;
}


export function pickInitialModel(p) {
  // while a profile routes, the head of the chain for this provider is the
  // only sensible "selected" model — never a random catalog entry
  const profile = state.settings.advancedProfiles ? activeProfile() : null;
  if (profile) {
    const item = sortedProfileItems(profile).find((x) => x.providerId === p.id && x.enabled !== false && providerModelGloballyEnabled(p, x.model, state.providerModels[p.id] || []));
    return item ? item.model : null;
  }
  const vis = visibleModelsFor(p);
  if (!vis.length) return null;
  const cur = state.active.providerId === p.id ? state.active.model : null;
  if (cur && vis.some((m) => m.id === cur)) return cur;
  if (p.defaultModel && vis.some((m) => m.id === p.defaultModel)) return p.defaultModel;
  return vis[0].id;
}

export async function setActive(providerId, model) {
  state.active = await api.setActive({ providerId, model });
  state.activeProfileId = null;
  recordChatDebug('other', 'Direct model selected', { providerId, model });
  return state.active;
}

export function sortedProfileCandidates(profile) {
  return sortedProfileItems(profile);
}

let chatsTimer = null;
export function touchChats() {
  clearTimeout(chatsTimer);
  chatsTimer = setTimeout(() => {
    api.setChats(state.chats.filter(isPersistentChat), state.activeId).catch(() => {});
  }, 350);
}

/* 1.7.0 hot path: persist ONE changed chat record instead of rewriting the
   whole conversation list. Streaming and debug-event stamps call this every
   few hundred ms; the payload stays proportional to one chat, not all of them. */
const chatWriter = createChatWriter(api.setChat, {
  getActiveId: () => state.activeId,
  onError: (error) => toast('Could not save conversation: ' + error.message, 'err'),
});
export function touchChat(chat) { if (isPersistentChat(chat)) chatWriter.queue(chat); }
export const flushChatWrites = () => chatWriter.flush();

export const activeChat = () => state.chats.find((c) => c.id === state.activeId) || null;
export const systemPromptById = (id) => (state.settings.systemPrompts || []).find((p) => p.id === id) || null;
export const defaultSystemPrompt = () => systemPromptById(state.settings.defaultSystemPromptId) || (state.settings.systemPrompts || [])[0] || null;
export const activeSystemPrompt = (chat = activeChat()) => systemPromptById(chat?.systemPromptId) || null;

/**
 * The prompt stack actually sent for a chat (1.6.6 hot-switch feature).
 * The chat's selected prompt is always first and always included; any extra
 * prompts the user enabled for this chat follow in list order. Disabled
 * prompts are simply not sent.
 */
export function enabledPromptsFor(chat = activeChat()) {
  const all = state.settings.systemPrompts || [];
  const defId = state.settings.defaultSystemPromptId;
  // Pure checkbox semantics (1.6.7): a chat sends exactly the prompts whose
  // boxes are ticked. New chats start with only the default ticked; anything
  // (including the default) can be unticked; all unticked = no system message.
  const ids = new Set(Array.isArray(chat?.enabledPromptIds) ? chat.enabledPromptIds : (defId ? [defId] : []));
  const ordered = [];
  const def = all.find((p) => p.id === defId);
  if (def && ids.has(def.id)) ordered.push(def);
  all.forEach((p) => { if (p.id !== defId && ids.has(p.id)) ordered.push(p); });
  return ordered.filter((p) => (p.content || '').trim());
}
export const isPromptEnabledFor = (chat, id) => enabledPromptsFor(chat).some((p) => p.id === id);

export function recordChatDebug(category, label, detail = null, chat = activeChat()) {
  if (!chat) return;
  if (!Array.isArray(chat.debugEvents)) chat.debugEvents = [];
  chat.debugEvents.push({ ts: new Date().toISOString(), category, label, detail });
  if (chat.debugEvents.length > 250) chat.debugEvents.splice(0, chat.debugEvents.length - 250);
  touchChat(chat);
}

export function addChatTraceId(traceId, chat = activeChat()) {
  if (!chat || !traceId) return;
  if (!Array.isArray(chat.debugTraceIds)) chat.debugTraceIds = [];
  if (!chat.debugTraceIds.includes(traceId)) chat.debugTraceIds.push(traceId);
  if (chat.debugTraceIds.length > 32) chat.debugTraceIds.splice(0, chat.debugTraceIds.length - 32);
  touchChat(chat);
}

export function newChatRecord() {
  const draft = findDraft(state.chats, state.tempMode);
  if (draft) { state.activeId = draft.id; return draft; }
  // 1.8.0: pinned flag + temporary mode (issues 3 & 4)
  const c = { id: Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4), title: 'New chat', modeId: 'simple-chat', messages: [], systemPromptId: state.settings.defaultSystemPromptId || null, enabledPromptIds: state.settings.defaultSystemPromptId ? [state.settings.defaultSystemPromptId] : [], debugTraceIds: [], debugEvents: [], branches: [], pinned: false, ephemeral: !!state.tempMode };
  state.chats.unshift(c);
  state.activeId = c.id;
  // single-chat upsert inserts unknown chats server-side, so even a new chat
  // does not need a full-list rewrite
  touchChat(c);
  return c;
}
