'use strict';

/*
 * archx-agent webui server (v2).
 *  - Serves the modular front-end from /public
 *  - Multi-provider: each provider = base URL + encrypted key + model curation
 *  - Proxies /api/providers/:id/models and /api/chat (SSE passthrough,
 *    including reasoning/thinking deltas)
 *  - Logs request activity in SQLite; detailed payloads remain encrypted at rest.
 */

const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const express = require('express');

const { listModels, chatCompletion, generateImage, speech, transcribe, ProxyError, listProviderAdapters } = require('./proxy.js');
const { capabilitiesFor, defaultTestBodyFor } = require('./capabilities.js');
const { webSearch, testEngines, DEFAULT_PRIORITY: SEARCH_DEFAULT_PRIORITY } = require('./websearch.js');
const { withRetry } = require('./retry.js');
const { maskKey } = require('./util.js');
const { platformDirs, configPath, manifestPath } = require('./paths.js');
const { Store } = require('./store.js');
const { Logger } = require('./logger.js');
const { listModes, getMode } = require('./modes/index.js');
const keys = require('./keys.js');
const { mountLibrary, saveGeneratedAsset } = require('./memory/library.js');

function resolveVendor(rel) {
  try {
    return require.resolve(rel);
  } catch {
    return null;
  }
}

const VENDOR = {
  markdownIt: resolveVendor('markdown-it/dist/markdown-it.min.js'),
  hljsJs: resolveVendor('@highlightjs/cdn-assets/highlight.min.js'),
  hljsCss: resolveVendor('@highlightjs/cdn-assets/styles/github-dark.min.css'),
};

const strArr = (v) =>
  Array.isArray(v)
    ? Array.from(new Set(v.filter((x) => typeof x === 'string' && x.trim()).map((x) => x.trim())))
    : null;

const normalizeProfileItems = (items) => Array.isArray(items) ? items
  .filter((x) => x && typeof x.providerId === 'string' && typeof x.model === 'string' && x.model.trim())
  .map((x, i) => ({
    providerId: x.providerId,
    model: x.model.trim(),
    priority: Number(x.priority) > 0 ? Math.floor(Number(x.priority)) : 1,
    order: Number.isFinite(Number(x.order)) ? Number(x.order) : i,
    enabled: x.enabled !== false,
    // 1.8.0: entries whose provider was deleted stay parked (paused) so the
    // chain can be restored when the provider is re-attached.
    parked: x.parked === true,
    parkedProviderName: typeof x.parkedProviderName === 'string' ? x.parkedProviderName : undefined,
  })) : [];

const normalizeProviderModels = (models) => {
  const src = models && typeof models === 'object' ? models : {};
  const catalog = strArr(src.catalog) || [];
  const hidden = strArr(src.hidden) || [];
  const custom = strArr(src.custom) || [];
  return {
    catalog,
    catalogInitialized: src.catalogInitialized === true,
    selectionMode: src.selectionMode === 'checklist' ? 'checklist' : 'legacy',
    hidden,
    custom,
    // 1.8.0: per-model capability overrides + custom test bodies (issue 7)
    capabilities: src.capabilities && typeof src.capabilities === 'object' ? src.capabilities : {},
    testBodies: src.testBodies && typeof src.testBodies === 'object' ? src.testBodies : {},
  };
};

function providerModelsOf(provider) {
  return normalizeProviderModels(provider?.models);
}

function providerModelIsEnabled(provider, modelId) {
  if (!provider) return false;
  const models = providerModelsOf(provider);
  const id = String(modelId || '').trim();
  if (!id) return false;
  const isCustom = models.custom.includes(id);
  if (models.selectionMode === 'checklist' && !models.catalog.includes(id) && !isCustom) return false;
  if (models.hidden.includes(id)) return false;
  if (provider.freeOnly) {
    const manuallyEnabled = Array.isArray(provider.freeOnlyManualEnabled) && provider.freeOnlyManualEnabled.includes(id);
    if (!manuallyEnabled && Array.isArray(provider.freeOnlyAutoHidden) && provider.freeOnlyAutoHidden.includes(id)) return false;
    if (!manuallyEnabled && !isCustom && !/(^|[:/_-])free$/i.test(id)) return false;
  }
  return true;
}

function activeProfileHead(store) {
  const profileId = store.state.providers.activeProfileId;
  if (!profileId) return null;
  const profile = (store.state.providers.profiles || []).find((x) => x.id === profileId);
  if (!profile) return null;
  return [...(profile.items || [])]
    .filter((item) => { const provider = store.provider(item.providerId); return item.enabled !== false && !!provider && providerModelIsEnabled(provider, item.model); })
    .sort((a, b) => (Number(a.priority) || 1) - (Number(b.priority) || 1) || (Number(a.order) || 0) - (Number(b.order) || 0))[0] || null;
}

function syncActiveSelection(store, changedProviderId = null) {
  const act = store.state.providers.active;
  if (store.state.providers.activeProfileId) {
    const first = activeProfileHead(store);
    if (first) {
      act.providerId = first.providerId;
      act.model = first.model;
    } else {
      act.model = null;
    }
    return;
  }
  if (changedProviderId && act.providerId === changedProviderId && act.model) {
    const p = store.provider(changedProviderId);
    if (!p || !providerModelIsEnabled(p, act.model)) act.model = null;
  }
}

function normalizeCatalogForProvider(provider, models) {
  const live = Array.isArray(models) ? models : [];
  const current = providerModelsOf(provider);
  if (current.catalogInitialized) return current;
  const catalog = current.selectionMode === 'legacy'
    ? live.map((m) => String(m?.id || '').trim()).filter(Boolean)
    : [];
  return { ...current, catalog: Array.from(new Set([...current.custom, ...catalog])), catalogInitialized: current.selectionMode === 'legacy' };
}

/* 1.8.0: the shipped default prompt uses template variables where they always
   resolve ({agentName} falls back to "Archx Agent"), and stays a simple,
   professional instruction set otherwise. It is fully editable in Settings →
   System prompts. */
const DEFAULT_SYSTEM_PROMPT = [
  'You are {agentName} — a sharp, practical and friendly AI assistant.',
  'Be clear, concrete and concise. When a request is ambiguous, ask one focused clarifying question instead of guessing.',
  'Never invent facts, tool results, citations or actions. Clearly separate what is known from what is assumed, and say so when you are assuming.',
  'For technical work, prefer correct, runnable examples and briefly explain the trade-offs that actually matter.',
  'Use the personalization context appended to this prompt (preferred name, age) naturally when it is relevant — never mention the context itself.',
].join('\n');

const normalizeSystemPrompts = (settings) => {
  const source = Array.isArray(settings.systemPrompts) ? settings.systemPrompts : [];
  const prompts = source.filter((p) => p && typeof p.content === 'string').map((p, i) => ({ id: typeof p.id === 'string' && p.id.trim() ? p.id.trim() : `sp-${i+1}`, name: typeof p.name === 'string' && p.name.trim() ? p.name.trim() : `Prompt ${i+1}`, content: p.content }));
  const legacy = typeof settings.system === 'string' ? settings.system : '';
  const initialized = settings.defaultSystemPromptInitialized === true;
  if (!prompts.length) prompts.push({ id:'sp-default', name:'Default', content: legacy || (!initialized ? DEFAULT_SYSTEM_PROMPT : '') });
  const wanted = typeof settings.defaultSystemPromptId === 'string' ? settings.defaultSystemPromptId : null;
  const defaultId = prompts.some(p=>p.id===wanted) ? wanted : prompts[0].id;
  if (!initialized) {
    const currentDefault = prompts.find((p) => p.id === defaultId);
    if (currentDefault && !(currentDefault.content || '').trim()) currentDefault.content = DEFAULT_SYSTEM_PROMPT;
  }
  return { prompts, defaultId, initialized: true };
};

const hostOf = (u) => {
  try {
    return new URL(u).host;
  } catch {
    return String(u || '');
  }
};

function createApp(opts = {}) {
  const store = opts.store || new Store(null);
  const logger = new Logger(store, () => store.state.settings.logsMode);
  const promptState = normalizeSystemPrompts(store.state.settings || {});
  const priorSettings = store.state.settings || {};
  const inferredOnboarded = priorSettings.personalizationOnboarded === true || !!String(priorSettings.preferredName || priorSettings.username || '').trim() || (String(priorSettings.agentName || '').trim() && String(priorSettings.agentName).trim() !== 'Archx Agent') || !!String(priorSettings.age || '').trim();
  store.state.settings = { ...priorSettings, systemPrompts: promptState.prompts, defaultSystemPromptId: promptState.defaultId, defaultSystemPromptInitialized: true, system: promptState.prompts.find(p=>p.id===promptState.defaultId)?.content || '', personalizationOnboarded: inferredOnboarded };
  if (store.state.settings.theme === 'funky') store.state.settings.theme = 'dark'; // 1.8.0: funky retired
  if (!store.state.settings.search || typeof store.state.settings.search !== 'object') {
    store.state.settings.search = { enabled: true, engines: [...SEARCH_DEFAULT_PRIORITY], maxResults: 5 };
  }
  if (store.dir) store.persist('settings');
  // 1.8.0 (issue 12): apply log retention at boot, then every 6 hours.
  const applyRetention = () => {
    const r = store.state.settings.logRetention;
    if (!r || !store.dir) return;
    const removed = store.purgeLogs(r);
    if (removed) console.log(`archx-agent: log retention purged ${removed} expired log row(s).`);
  };
  applyRetention();
  setInterval(applyRetention, 6 * 3600 * 1000).unref?.();
  const app = express();
  app.disable('x-powered-by');
  app.use(express.json({ limit: '32mb' }));

  // ---- static front-end -------------------------------------------------
  app.use(express.static(path.join(__dirname, '..', 'public'), { index: 'index.html' }));

  const send = (file, type) => (req, res) => {
    if (!file) return res.status(404).type('text/plain').send('/* not bundled */');
    res.type(type).set('Cache-Control', 'public, max-age=86400').sendFile(file);
  };
  app.get('/vendor/markdown-it.min.js', send(VENDOR.markdownIt, 'application/javascript'));
  app.get('/vendor/hljs.min.js', send(VENDOR.hljsJs, 'application/javascript'));
  app.get('/vendor/hljs.css', send(VENDOR.hljsCss, 'text/css'));

  // ---- views --------------------------------------------------------------
  const providerView = (p) => {
    let hasKey = !!p.keyCipher;
    let keyMasked = null;
    let keyError = false;
    if (hasKey) {
      try {
        keyMasked = maskKey(store.keyOf(p));
      } catch {
        keyError = true; // fingerprint changed / cipher corrupt
      }
    }
    return {
      id: p.id,
      name: p.name,
      adapter: p.adapter || 'openai-compatible',
      baseUrl: p.baseUrl,
      host: hostOf(p.baseUrl),
      hasKey,
      keyMasked,
      keyError,
      freeOnly: !!p.freeOnly,
      freeOnlySnapshot: Array.isArray(p.freeOnlySnapshot) ? p.freeOnlySnapshot : [],
      defaultModel: p.defaultModel || null,
      models: providerModelsOf(p),
      freeOnlyAutoHidden: Array.isArray(p.freeOnlyAutoHidden) ? p.freeOnlyAutoHidden : [],
      freeOnlyManualEnabled: Array.isArray(p.freeOnlyManualEnabled) ? p.freeOnlyManualEnabled : [],
    };
  };

  const storageView = () => ({
    dir: store.dir,
    memoryOnly: store.memoryOnly,
    configPath: configPath(),
    suggestions: {
      default: platformDirs().data,
      local: path.join(process.cwd(), '.archx-agent'),
    },
    database: store.dir ? path.join(store.dir, 'archx.db') : null,
    manifestPath: manifestPath(),
    manifest: store.getManifest(),
  });

  const persistProviders = () => store.persist('providers');
  let providerDefaultsChanged = false;
  for (const p of store.state.providers.providers) {
    if (/openrouter\.ai$/i.test(hostOf(p.baseUrl)) && !p.defaultModel) {
      p.defaultModel='openrouter/free';
      p.models=p.models||{};
      if(!Array.isArray(p.models.custom)) p.models.custom=[];
      if(!p.models.custom.includes('openrouter/free')) p.models.custom.unshift('openrouter/free');
      providerDefaultsChanged=true;
    }
    if (!p.adapter) { p.adapter = 'openai-compatible'; providerDefaultsChanged = true; }
    if (!listProviderAdapters().includes(String(p.adapter).toLowerCase())) { p.adapter = 'openai-compatible'; providerDefaultsChanged = true; }
    if (!p.models || typeof p.models !== 'object') { p.models = {}; providerDefaultsChanged = true; }
    if (!Array.isArray(p.models.catalog)) { p.models.catalog = []; providerDefaultsChanged = true; }
    if (!Array.isArray(p.models.hidden)) { p.models.hidden = []; providerDefaultsChanged = true; }
    if (!Array.isArray(p.models.custom)) { p.models.custom = []; providerDefaultsChanged = true; }
    if (typeof p.models.catalogInitialized !== 'boolean') {
      // 1.6.7 providers used the live provider list as their catalog. Keep
      // that behavior for existing installations; newly added providers use
      // the explicit checklist flow below.
      p.models.catalogInitialized = false;
      p.models.selectionMode = p.models.selectionMode || 'legacy';
      providerDefaultsChanged = true;
    } else if (!p.models.selectionMode) {
      p.models.selectionMode = p.models.catalogInitialized ? 'checklist' : 'legacy';
      providerDefaultsChanged = true;
    }
    p.models.hidden = strArr(p.models.hidden) || [];
    p.models.catalog = strArr(p.models.catalog) || [];
    p.models.custom = strArr(p.models.custom) || [];
    if(!Array.isArray(p.freeOnlySnapshot)) { p.freeOnlySnapshot=[]; providerDefaultsChanged=true; }
    if(!Array.isArray(p.freeOnlyAutoHidden)) { p.freeOnlyAutoHidden=[]; providerDefaultsChanged=true; }
    if(!Array.isArray(p.freeOnlyManualEnabled)) { p.freeOnlyManualEnabled=[]; providerDefaultsChanged=true; }
  }
  if (!Array.isArray(store.state.providers.profiles)) { store.state.providers.profiles = []; providerDefaultsChanged = true; }
  const validProviderIds = new Set(store.state.providers.providers.map((p) => p.id));
  const usedProfileNames = new Set();
  store.state.providers.profiles = store.state.providers.profiles.map((profile, index) => {
    const legacyItems = Array.isArray(profile.models) && profile.providerId
      ? profile.models.map((model, i) => ({ providerId: profile.providerId, model, priority: 1, order: i }))
      : [];
    const source = Array.isArray(profile.items) ? profile.items : legacyItems;
    const requestedName = typeof profile.name === 'string' ? profile.name.trim() : '';
    const baseName = requestedName || `Profile ${index + 1}`;
    let normalizedName = baseName;
    let suffix = 2;
    while (usedProfileNames.has(normalizedName.toLocaleLowerCase())) normalizedName = `${baseName} (${suffix++})`;
    usedProfileNames.add(normalizedName.toLocaleLowerCase());
    if (normalizedName !== requestedName || !requestedName) providerDefaultsChanged = true;
    const normalized = {
      id: profile.id || 'mp-' + crypto.randomBytes(4).toString('hex'),
      name: normalizedName,
      description: typeof profile.description === 'string' ? profile.description : '',
      items: source
        .filter((x) => x && (validProviderIds.has(x.providerId) || x.parked === true) && typeof x.model === 'string' && x.model.trim())
        .map((x, i) => ({ providerId: x.providerId, model: x.model.trim(), priority: Number(x.priority) > 0 ? Math.floor(Number(x.priority)) : 1, order: Number.isFinite(Number(x.order)) ? Number(x.order) : i, enabled: x.enabled !== false, parked: x.parked === true, parkedProviderName: typeof x.parkedProviderName === 'string' ? x.parkedProviderName : undefined })),
    };
    if (!Array.isArray(profile.items) || profile.providerId || profile.models) providerDefaultsChanged = true;
    return normalized;
  });
  if (store.state.providers.activeProfileId && !store.state.providers.profiles.some((x) => x.id === store.state.providers.activeProfileId)) {
    store.state.providers.activeProfileId = null;
    providerDefaultsChanged = true;
  }
  if(providerDefaultsChanged) persistProviders();

  // ---- api: state ----------------------------------------------------------
  const bootTime = Date.now();
  app.get('/api/health', (req, res) => {
    res.json({
      ok: true,
      name: 'archx-agent',
      version: require('../package.json').version,
      uptimeMs: Date.now() - bootTime,
      startedAt: new Date(bootTime).toISOString(),
    });
  });

  // ---- api: logs -------------------------------------------------------------
  app.get('/api/logs', (req, res) => {
    const limit = Math.min(2000, Math.max(1, Number(req.query.limit) || 400));
    const entries = store.listLogs({ limit });
    res.json({ database: store.dir ? path.join(store.dir, 'archx.db') : null, entries, mode: store.state.settings.logsMode || 'simple', rev: store.logsRev().rev });
  });

  /* Lightweight journal revision probe. Pollers (debug page, chat debug)
     call this every few seconds and only re-fetch the full log list when the
     revision changed — one indexed aggregate instead of shipping hundreds of
     payloads per poll. */
  app.get('/api/logs/rev', (req, res) => {
    const r = store.logsRev();
    res.json({ ...r, mode: store.state.settings.logsMode || 'simple' });
  });

  app.get('/api/chat-debug', (req, res) => {
    const traceIds = String(req.query.traceIds || req.query.traceId || '')
      .split(',').map(x => x.trim()).filter(Boolean).slice(0, 32);
    const chatId = String(req.query.chatId || '').trim();
    const limit = Math.min(1500, Math.max(1, Number(req.query.limit) || 600));
    if (!store.dir || (!traceIds.length && !chatId)) return res.json({ apiCalls: [], tools: [], other: [], providers: [] });
    const entries = store.listLogs({ limit, traceIds, chatId: chatId || null });
    const isApi = (e) => !!(e.providerId || e.provider || String(e.kind || '').startsWith('chat'));
    const isTool = (e) => String(e.kind || '').startsWith('tool');
    const apiCalls = entries.filter(isApi);
    const tools = entries.filter(isTool);
    const other = entries.filter(e => !isApi(e) && !isTool(e));
    const providers = [...new Set(apiCalls.map(e => e.provider || e.providerId).filter(Boolean))];
    res.json({ apiCalls, tools, other, providers, rev: store.logsRev().rev });
  });

  app.delete('/api/logs', (req, res) => { store.clearLogs(); res.json({ ok: true }); });

  app.get('/api/state', (req, res) => {
    res.json({
      storage: storageView(),
      providers: store.state.providers.providers.map(providerView),
      active: store.state.providers.active,
      profiles: store.state.providers.profiles || [],
      activeProfileId: store.state.providers.activeProfileId || null,
      settings: store.state.settings,
      providerAdapters: listProviderAdapters(),
      modes: listModes(),
      chats: store.state.chats.chats,
      activeId: store.state.chats.activeId,
    });
  });

  app.post('/api/state/settings', (req, res) => {
    const b = req.body || {};
    const cur = { ...store.state.settings };
    if (Array.isArray(b.systemPrompts)) { const ps=normalizeSystemPrompts({ ...cur, systemPrompts:b.systemPrompts, defaultSystemPromptId:b.defaultSystemPromptId }); cur.systemPrompts=ps.prompts; cur.defaultSystemPromptId=ps.defaultId; cur.system=ps.prompts.find(p=>p.id===ps.defaultId)?.content||''; }
    else if (typeof b.system === 'string') cur.system = b.system;
    if (typeof b.temperature === 'number' && !Number.isNaN(b.temperature)) {
      cur.temperature = Math.min(2, Math.max(0, b.temperature));
    }
    if ('maxTokens' in b) cur.maxTokens = b.maxTokens ? Number(b.maxTokens) : null;
    if (typeof b.stream === 'boolean') cur.stream = b.stream;
    // 1.8.0 (issue 15): the funky theme was retired — existing installs are
    // normalized to dark on load.
    if (b.theme === 'dark' || b.theme === 'light' || b.theme === 'soft') cur.theme = b.theme;
    if (b.logsMode === 'simple' || b.logsMode === 'detailed-encrypted') cur.logsMode = b.logsMode;
    if (b.logRetention && typeof b.logRetention === 'object') {
      const numOrNull = (v) => { const n = Number(v); return Number.isFinite(n) && n > 0 ? n : null; };
      cur.logRetention = {
        allDays: numOrNull(b.logRetention.allDays),
        apiDays: numOrNull(b.logRetention.apiDays),
        toolsDays: numOrNull(b.logRetention.toolsDays),
        configDays: numOrNull(b.logRetention.configDays),
      };
    }
    if (b.search && typeof b.search === 'object') {
      const cur0 = cur.search && typeof cur.search === 'object' ? cur.search : {};
      const engines = Array.isArray(b.search.engines) && b.search.engines.length
        ? b.search.engines.filter((x) => ['ddg', 'bing', 'searxng'].includes(x))
        : (Array.isArray(cur0.engines) && cur0.engines.length ? cur0.engines : SEARCH_DEFAULT_PRIORITY);
      cur.search = {
        enabled: b.search.enabled !== false,
        engines,
        maxResults: Math.min(10, Math.max(1, Number(b.search.maxResults) || Number(cur0.maxResults) || 5)),
      };
    }
    if (typeof b.advancedProfiles === 'boolean') cur.advancedProfiles = b.advancedProfiles;
    if (b.systemPromptMode === 'replace' || b.systemPromptMode === 'stack') cur.systemPromptMode = b.systemPromptMode;
    for (const key of ['username', 'age', 'preferredName', 'agentName']) {
      if (typeof b[key] === 'string') cur[key] = b[key].trim();
    }
    if (typeof b.personalizationOnboarded === 'boolean') cur.personalizationOnboarded = b.personalizationOnboarded;
    if (!cur.agentName) cur.agentName = 'Archx Agent';
    store.set('settings', cur);
    res.json({ settings: cur });
  });

  app.post('/api/state/chats', (req, res) => {
    const b = req.body || {};
    if (!Array.isArray(b.chats)) return res.status(400).json({ error: { message: 'chats[] required' } });
    if (b.chats.some(c => {
      const previous = store.state.chats.chats.find(p => p.id === c.id);
      return !getMode(c.modeId || 'simple-chat') || (previous?.modeId && previous.modeId !== 'simple-chat' && c.modeId !== previous.modeId);
    })) return res.status(409).json({ error: { message: 'Conversation mode is unavailable or locked.' } });
    store.set('chats', { chats: b.chats.filter(c => !c.ephemeral), activeId: typeof b.activeId === 'string' ? b.activeId : null });
    res.json({ ok: true });
  });

  /* Hot-path persistence: while streaming, only ONE chat record changes.
     Rewriting the whole chat list (every message of every chat) on each
     debounced touch was the single heaviest client→server payload in the app.
     This upserts just the changed chat. */
  app.post('/api/state/chat', (req, res) => {
    const b = req.body || {};
    if (!b.chat || typeof b.chat.id !== 'string') return res.status(400).json({ error: { message: 'chat{id} required' } });
    const previous = store.state.chats.chats.find(c => c.id === b.chat.id);
    if (!getMode(b.chat.modeId || 'simple-chat') || (previous?.modeId && previous.modeId !== 'simple-chat' && b.chat.modeId !== previous.modeId)) return res.status(409).json({ error: { message: 'Conversation mode is unavailable or locked.' } });
    store.upsertChat(b.chat, typeof b.activeId === 'string' ? b.activeId : undefined);
    res.json({ ok: true });
  });

  // ---- api: providers -------------------------------------------------------
  app.post('/api/providers', (req, res) => {
    const { name, baseUrl, apiKey, adapter } = req.body || {};
    if (typeof baseUrl !== 'string' || !baseUrl.trim()) {
      return res.status(400).json({ error: { message: 'baseUrl is required.' } });
    }
    const clean = baseUrl.trim().replace(/\/+$/, '');
    const providerAdapter = typeof adapter === 'string' && adapter.trim() ? adapter.trim().toLowerCase() : 'openai-compatible';
    if (!listProviderAdapters().includes(providerAdapter)) return res.status(400).json({ error: { message: `Unknown provider adapter “${providerAdapter}”.` } });
    const p = {
      id: 'p-' + crypto.randomBytes(4).toString('hex'),
      name: (name || '').trim() || hostOf(clean),
      adapter: providerAdapter,
      baseUrl: clean,
      keyCipher: apiKey && String(apiKey).trim() ? keys.encrypt(String(apiKey).trim()) : null,
      models: { catalog: [], catalogInitialized: false, selectionMode: 'checklist', hidden: [], custom: [] },
      freeOnly: false,
      freeOnlySnapshot: [],
      freeOnlyAutoHidden: [],
      freeOnlyManualEnabled: [],
      defaultModel: /openrouter\.ai$/i.test(hostOf(clean)) ? 'openrouter/free' : null,
    };
    if (p.defaultModel) p.models.custom.push(p.defaultModel);
    store.state.providers.providers.push(p);
    if (!store.state.providers.active.providerId) {
      store.state.providers.active.providerId = p.id;
    }
    /* 1.8.0 (issue 5): re-attaching a provider re-binds parked profile entries
       that were paused when the same provider was deleted. They stay paused —
       one click in the profile resumes them. */
    let reattached = 0;
    for (const profile of store.state.providers.profiles || []) {
      profile.items = (profile.items || []).map((item) => {
        if (item.parked === true && item.parkedProviderName === p.name) {
          reattached += 1;
          return { ...item, providerId: p.id, parked: false, parkedProviderName: undefined, enabled: false };
        }
        return item;
      });
    }
    persistProviders();
    logger.log({ kind: 'provider-add', providerId: p.id, provider: p.name, baseUrl: p.baseUrl, hasKey: !!p.keyCipher, reattached });
    res.json({ provider: providerView(p), active: store.state.providers.active, profiles: store.state.providers.profiles, reattached });
  });

  app.patch('/api/providers/:id', (req, res) => {
    const p = store.provider(req.params.id);
    if (!p) return res.status(404).json({ error: { message: 'Unknown provider.' } });
    const b = req.body || {};
    if (typeof b.name === 'string' && b.name.trim()) p.name = b.name.trim();
    if (typeof b.adapter === 'string' && b.adapter.trim()) {
      const adapter = b.adapter.trim().toLowerCase();
      if (!listProviderAdapters().includes(adapter)) return res.status(400).json({ error: { message: `Unknown provider adapter “${adapter}”.` } });
      p.adapter = adapter;
    }
    if (typeof b.baseUrl === 'string' && b.baseUrl.trim()) p.baseUrl = b.baseUrl.trim().replace(/\/+$/, '');
    if (b.clearKey) p.keyCipher = null;
    else if (typeof b.apiKey === 'string' && b.apiKey.trim()) p.keyCipher = keys.encrypt(b.apiKey.trim());
    if (typeof b.freeOnly === 'boolean') p.freeOnly = b.freeOnly;
    if (Array.isArray(b.freeOnlySnapshot)) p.freeOnlySnapshot = strArr(b.freeOnlySnapshot) || [];
    if (Array.isArray(b.freeOnlyAutoHidden)) p.freeOnlyAutoHidden = strArr(b.freeOnlyAutoHidden) || [];
    if (Array.isArray(b.freeOnlyManualEnabled)) p.freeOnlyManualEnabled = strArr(b.freeOnlyManualEnabled) || [];
    if (typeof b.defaultModel === 'string' && b.defaultModel.trim()) p.defaultModel = b.defaultModel.trim();
    if (b.models && typeof b.models === 'object') {
      const current = providerModelsOf(p);
      const hidden = strArr(b.models.hidden);
      const custom = strArr(b.models.custom);
      const catalog = strArr(b.models.catalog);
      p.models = {
        catalog: catalog !== null ? catalog : current.catalog,
        catalogInitialized: typeof b.models.catalogInitialized === 'boolean' ? b.models.catalogInitialized : current.catalogInitialized,
        selectionMode: b.models.selectionMode === 'legacy' || b.models.selectionMode === 'checklist' ? b.models.selectionMode : (current.selectionMode || (current.catalogInitialized ? 'checklist' : 'legacy')),
        hidden: hidden !== null ? hidden : current.hidden,
        custom: custom !== null ? custom : current.custom,
        capabilities: b.models.capabilities && typeof b.models.capabilities === 'object' ? b.models.capabilities : current.capabilities,
        testBodies: b.models.testBodies && typeof b.models.testBodies === 'object' ? b.models.testBodies : current.testBodies,
      };
    }
    syncActiveSelection(store, p.id);
    persistProviders();
    logger.log({ kind: 'provider-update', providerId: p.id, provider: p.name, fields: Object.keys(b).filter((k) => k !== 'apiKey') });
    res.json({ provider: providerView(p) });
  });

  app.delete('/api/providers/:id', (req, res) => {
    const before = store.state.providers.providers.length;
    const deletedProvider = store.provider(req.params.id);
    store.state.providers.providers = store.state.providers.providers.filter((p) => p.id !== req.params.id);
    if (store.state.providers.providers.length === before) {
      return res.status(404).json({ error: { message: 'Unknown provider.' } });
    }
    const act = store.state.providers.active;
    if (act.providerId === req.params.id) {
      act.providerId = store.state.providers.providers[0] ? store.state.providers.providers[0].id : null;
      act.model = null;
    }
    /* 1.8.0 (issue 5): deleting a provider no longer silently rips its models
       out of profiles. "pause" (default) keeps every profile entry but paused
       + marked parked, so re-attaching the same provider later restores the
       chain as-is (the UI offers a one-click Resume). "remove" deletes them. */
    const policy = req.body && req.body.modelPolicy === 'remove' ? 'remove' : 'pause';
    store.state.providers.profiles = (store.state.providers.profiles || [])
      .map((x) => ({
        ...x,
        items: (x.items || [])
          .filter((item) => item.providerId !== req.params.id || policy === 'pause')
          .map((item) => item.providerId === req.params.id ? { ...item, enabled: false, parked: true, parkedProviderName: deletedProvider ? deletedProvider.name : item.providerId } : item),
      }))
      .filter((x) => (x.items || []).length > 0);
    if (store.state.providers.activeProfileId && !store.state.providers.profiles.some((x) => x.id === store.state.providers.activeProfileId)) {
      store.state.providers.activeProfileId = null;
    }
    persistProviders();
    logger.log({ kind: 'provider-remove', providerId: req.params.id });
    res.json({ providers: store.state.providers.providers.map(providerView), active: act, profiles: store.state.providers.profiles, activeProfileId: store.state.providers.activeProfileId });
  });

  // ---- api: model profiles --------------------------------------------------
  const profileNameTaken = (name, exceptId = null) => {
    const key = String(name || '').trim().toLocaleLowerCase();
    return (store.state.providers.profiles || []).some((profile) => profile.id !== exceptId && String(profile.name || '').trim().toLocaleLowerCase() === key);
  };

  app.post('/api/profiles', (req, res) => {
    const b = req.body || {};
    const name = typeof b.name === 'string' ? b.name.trim() : '';
    if (!name) return res.status(400).json({ error: { message: 'Profile name is required.' } });
    if (profileNameTaken(name)) return res.status(409).json({ error: { message: 'A profile with that name already exists. Profile names must be unique.' } });
    const items = normalizeProfileItems(Array.isArray(b.items) ? b.items : []);
    if (items.some((item) => !item.parked && !store.provider(item.providerId))) return res.status(400).json({ error: { message: 'Profile contains an unknown provider.' } });
    const profile = { id: 'mp-' + crypto.randomBytes(4).toString('hex'), name, description: typeof b.description === 'string' ? b.description : '', items };
    if (!Array.isArray(store.state.providers.profiles)) store.state.providers.profiles = [];
    store.state.providers.profiles.push(profile);
    persistProviders();
    res.json({ profile, profiles: store.state.providers.profiles, activeProfileId: store.state.providers.activeProfileId || null });
  });

  app.patch('/api/profiles/:id', (req, res) => {
    const profile = (store.state.providers.profiles || []).find((x) => x.id === req.params.id);
    if (!profile) return res.status(404).json({ error: { message: 'Unknown model profile.' } });
    const b = req.body || {};
    if (typeof b.name === 'string') {
      const name = b.name.trim();
      if (!name) return res.status(400).json({ error: { message: 'Profile name is required.' } });
      if (profileNameTaken(name, profile.id)) return res.status(409).json({ error: { message: 'A profile with that name already exists. Profile names must be unique.' } });
      profile.name = name;
    }
    if (typeof b.description === 'string') profile.description = b.description;
    if (Array.isArray(b.items)) {
      const items = normalizeProfileItems(b.items);
      if (items.some((item) => !item.parked && !store.provider(item.providerId))) return res.status(400).json({ error: { message: 'Profile contains an unknown provider.' } });
      profile.items = items;
    }
    syncActiveSelection(store);
    persistProviders();
    res.json({ profile, profiles: store.state.providers.profiles, activeProfileId: store.state.providers.activeProfileId || null, active: store.state.providers.active });
  });

  app.delete('/api/profiles/:id', (req, res) => {
    const before = (store.state.providers.profiles || []).length;
    store.state.providers.profiles = (store.state.providers.profiles || []).filter((x) => x.id !== req.params.id);
    if (before === store.state.providers.profiles.length) return res.status(404).json({ error: { message: 'Unknown model profile.' } });
    if (store.state.providers.activeProfileId === req.params.id) store.state.providers.activeProfileId = null;
    persistProviders();
    res.json({ profiles: store.state.providers.profiles, activeProfileId: store.state.providers.activeProfileId || null });
  });

  app.post('/api/active-profile', (req, res) => {
    const id = req.body && req.body.profileId;
    if (id !== null && id !== undefined && id !== '' && !(store.state.providers.profiles || []).some((x) => x.id === id)) {
      return res.status(404).json({ error: { message: 'Unknown model profile.' } });
    }
    store.state.providers.activeProfileId = id || null;
    syncActiveSelection(store);
    // Clearing a profile returns to the last direct provider/model selection rather than
    // wiping the model. This also lets the Advanced Profiles toggle be reversed safely.
    persistProviders();
    res.json({ active: store.state.providers.active, activeProfileId: store.state.providers.activeProfileId, profiles: store.state.providers.profiles });
  });

  app.post('/api/active', (req, res) => {
    const { providerId, model } = req.body || {};
    const act = store.state.providers.active;
    if (providerId !== undefined) {
      if (providerId !== null && !store.provider(providerId)) return res.status(404).json({ error: { message: 'Unknown provider.' } });
      act.providerId = providerId;
      act.model = null;
    }
    if (typeof model === 'string' && model) {
      const provider = store.provider(act.providerId);
      if (!provider || !providerModelIsEnabled(provider, model)) {
        return res.status(400).json({ error: { message: 'That model is disabled or not in this provider list.' } });
      }
      act.model = model;
    }
    // Explicit direct model selection leaves profile mode, so the next request is not forced through a profile.
    store.state.providers.activeProfileId = null;
    persistProviders();
    res.json({ active: act });
  });

  app.post('/api/provider-test', async (req, res) => {
    const baseUrl = typeof req.body?.baseUrl === 'string' ? req.body.baseUrl.trim().replace(/\/+$/, '') : '';
    const apiKey = typeof req.body?.apiKey === 'string' && req.body.apiKey.trim() ? req.body.apiKey.trim() : null;
    const adapter = typeof req.body?.adapter === 'string' && req.body.adapter.trim() ? req.body.adapter.trim().toLowerCase() : 'openai-compatible';
    if (!baseUrl) return res.status(400).json({ error: { message: 'baseUrl is required.' } });
    if (!listProviderAdapters().includes(adapter)) return res.status(400).json({ error: { message: `Unknown provider adapter “${adapter}”.` } });
    const t0 = Date.now();
    try {
      const models = await withRetry(() => listModels({ adapter, baseUrl, apiKey, timeoutMs: 10000 }), { attempts: 2 });
      res.json({ ok:true, reachable:true, modelCount:models.length, ms:Date.now()-t0 });
    } catch (err) {
      const status=err instanceof ProxyError?err.status:502;
      res.status(status).json({ error:{message:err.message,upstream:err.upstream}, reachable:false });
    }
  });

  app.post('/api/providers/:id/test', async (req, res) => {
    const p = store.provider(req.params.id);
    if (!p) return res.status(404).json({ error: { message: 'Unknown provider.' } });
    let apiKey = null;
    try { apiKey = store.keyOf(p); } catch { return res.status(400).json({ error: { message: 'Stored key could not be decrypted — re-enter it.' } }); }
    const t0 = Date.now();
    try {
      const models = await listModels({ adapter: p.adapter, baseUrl: p.baseUrl, apiKey, timeoutMs: 10000 });
      logger.log({ kind: 'provider-test', providerId: p.id, provider: p.name, baseUrl: p.baseUrl, status: 200, ms: Date.now() - t0, count: models.length }, { request: { method: 'GET', path: '/models' }, response: { count: models.length, data: models } });
      res.json({ ok: true, reachable: true, modelCount: models.length, ms: Date.now() - t0 });
    } catch (err) {
      const status = err instanceof ProxyError ? err.status : 502;
      logger.log({ kind: 'provider-test', providerId: p.id, provider: p.name, status, ms: Date.now() - t0, error: err.message }, { request: { method: 'GET', path: '/models' }, response: null, upstream: err.upstream });
      res.status(status).json({ error: { message: err.message, upstream: err.upstream }, reachable: false });
    }
  });

  app.post('/api/providers/:id/models', async (req, res) => {
    const p = store.provider(req.params.id);
    if (!p) return res.status(404).json({ error: { message: 'Unknown provider.' } });
    let apiKey = null;
    try {
      apiKey = store.keyOf(p);
    } catch {
      return res.status(400).json({
        error: { message: 'Stored key could not be decrypted on this machine — re-enter the key for this provider.' },
      });
    }
    const t0 = Date.now();
    try {
      const models = await listModels({ adapter: p.adapter, baseUrl: p.baseUrl, apiKey });
      if (!providerModelsOf(p).catalogInitialized && providerModelsOf(p).selectionMode === 'legacy') {
        p.models = { ...providerModelsOf(p), catalog: normalizeCatalogForProvider(p, models).catalog, catalogInitialized: true, selectionMode: 'checklist' };
        persistProviders();
      }
      const catalogState = providerModelsOf(p);
      logger.log({ kind: 'models', providerId: p.id, provider: p.name, status: 200, ms: Date.now() - t0, count: models.length }, { request: { method: 'GET', path: '/models' }, response: { count: models.length, data: models, catalog: catalogState.catalog } });
      res.json({ object: 'list', data: models, catalog: catalogState.catalog, catalogInitialized: catalogState.catalogInitialized, selectionMode: catalogState.selectionMode });
    } catch (err) {
      const status = err instanceof ProxyError ? err.status : 502;
      logger.log({ kind: 'models', providerId: p.id, provider: p.name, status, ms: Date.now() - t0, error: err.message }, { request: { method: 'GET', path: '/models' }, response: null, upstream: err.upstream });
      res.status(status).json({ error: { message: err.message, upstream: err.upstream } });
    }
  });

  /* 1.8.0 capability-aware model probe (issue 7): the probe exercises the
     surface the model advertises — text models get a text probe, vision
     models text+a small image, image generators a generation request, TTS a
     synthesis request, STT a transcription (or reachability when no audio
     sample is configured). The request body comes from the shipped default
     test documents, or from the user-saved custom body for that model. */
  function probeBodyFor(p, model, reqBody = {}) {
    const models = providerModelsOf(p);
    const override = models.capabilities?.[model];
    const caps = capabilitiesFor(model, override);
    const saved = models.testBodies?.[model];
    const def = defaultTestBodyFor(model, override);
    const body = { kind: def.kind, message: def.body.message || null, prompt: def.body.prompt || null, input: def.body.input || null, image: def.body.image || null, imageMime: def.body.imageMime || null, audio: def.body.audio || null };
    if (saved && typeof saved === 'object') Object.assign(body, saved);
    if (typeof reqBody.message === 'string' && reqBody.message.trim()) { body.message = reqBody.message.trim(); if (body.kind === 'chat' || body.kind === 'vision') body.prompt = null; }
    if (typeof reqBody.prompt === 'string' && reqBody.prompt.trim()) body.prompt = reqBody.prompt.trim();
    if (typeof reqBody.input === 'string' && reqBody.input.trim()) body.input = reqBody.input.trim();
    return { body, caps };
  }

  async function probeModel(p, apiKey, model, reqBody = {}) {
    const { body } = probeBodyFor(p, model, reqBody);
    const t0 = Date.now();
    const attempts = Math.max(1, Math.min(4, Number(reqBody.attempts) || 2));
    const base = { adapter: p.adapter, baseUrl: p.baseUrl, apiKey, model };
    if (body.kind === 'tts') {
      const result = await speech({ ...base, input: body.input || 'Archx agent audio check.', timeoutMs: 30000 });
      return { ok: true, ms: Date.now() - t0, kind: 'tts', reply: `(audio ${Math.round((result.base64 || '').length * 0.75)} bytes)`, sent: { input: body.input }, received: { mime: result.mime, bytes: Math.round((result.base64 || '').length * 0.75) } };
    }
    if (body.kind === 'imageGen') {
      const result = await generateImage({ ...base, prompt: body.prompt || 'A minimal white letter A on a black square.', image: body.image || undefined, imageMime: body.imageMime, timeoutMs: 60000 });
      return { ok: true, ms: Date.now() - t0, kind: 'imageGen', reply: '(image generated)', sent: { prompt: body.prompt }, received: { mime: result.mime, bytes: Math.round((result.base64 || '').length * 0.75) } };
    }
    if (body.kind === 'stt') {
      if (body.audio) {
        const result = await transcribe({ ...base, audio: body.audio, mime: body.audioMime || 'audio/mpeg', timeoutMs: 60000 });
        return { ok: true, ms: Date.now() - t0, kind: 'stt', reply: result.text, sent: { audio: '(base64 sample)' }, received: { text: String(result.text).slice(0, 300) } };
      }
      const models = await listModels({ adapter: p.adapter, baseUrl: p.baseUrl, apiKey, timeoutMs: 15000 });
      return { ok: true, ms: Date.now() - t0, kind: 'stt', reply: `(reachable · ${models.length} models exposed · no audio sample configured)`, sent: { note: 'reachability probe' }, received: { models: models.length } };
    }
    if (body.kind === 'vision') {
      const content = [{ type: 'text', text: body.message || 'Describe this image in one word.' }];
      if (body.image) content.push({ type: 'image_url', image_url: { url: `data:${body.imageMime || 'image/png'};base64,${body.image}` } });
      const result = await withRetry(() => chatCompletion({ ...base, messages: [{ role: 'user', content }], stream: false, temperature: 0, timeoutMs: 30000 }), { attempts });
      return { ok: true, ms: Date.now() - t0, kind: 'vision', reply: result.text, sent: { content }, received: { text: String(result.text || '').slice(0, 300) } };
    }
    const result = await withRetry(() => chatCompletion({ ...base, messages: [{ role: 'user', content: body.message || 'Reply with exactly: ARCHX_OK' }], stream: false, temperature: 0, timeoutMs: 20000 }), { attempts });
    return { ok: true, ms: Date.now() - t0, kind: 'chat', reply: result.text, reasoning: result.reasoning || '', sent: { message: body.message }, received: { text: String(result.text || '').slice(0, 300) } };
  }

  app.post('/api/providers/:id/test-model', async (req, res) => {
    const p = store.provider(req.params.id);
    if (!p) return res.status(404).json({ error: { message: 'Unknown provider.' } });
    const model = typeof req.body?.model === 'string' ? req.body.model.trim() : '';
    if (!model) return res.status(400).json({ error: { message: 'model is required.' } });
    let apiKey = null;
    try { apiKey = store.keyOf(p); } catch { return res.status(400).json({ error: { message: 'Stored key could not be decrypted — re-enter it.' } }); }
    const silent = req.body?.silent === true; // batch orchestration logs once, at the end
    const t0 = Date.now();
    try {
      const result = await probeModel(p, apiKey, model, req.body || {});
      if (!silent) logger.log({ kind: 'model-test', providerId: p.id, provider: p.name, model, status: 200, ms: result.ms, probe: result.kind }, { request: result.sent, response: result.received });
      res.json({ ok: true, model, reply: result.reply, reasoning: result.reasoning || '', ms: Date.now() - t0, probe: result.kind, sent: result.sent, received: result.received });
    } catch (err) {
      const status = err instanceof ProxyError ? err.status : 502;
      if (!silent) logger.log({ kind: 'model-test', providerId: p.id, provider: p.name, model, status, ms: Date.now() - t0, error: err.message }, { error: err.message, upstream: err.upstream });
      res.status(status).json({ error: { message: err.message, upstream: err.upstream }, model });
    }
  });

  /* 1.8.0 (issue 12): the batch run itself writes ONE provider-level log. */
  app.post('/api/providers/:id/test-batch-log', (req, res) => {
    const p = store.provider(req.params.id);
    if (!p) return res.status(404).json({ error: { message: 'Unknown provider.' } });
    const b = req.body || {};
    const results = Array.isArray(b.results) ? b.results : [];
    const passed = results.filter((r) => r && r.ok).length;
    logger.log({
      kind: 'model-test-batch', providerId: p.id, provider: p.name, status: 200,
      count: results.length, passed, failed: results.length - passed,
      stopped: b.stopped === true,
      models: results.map((r) => ({ model: r.model, ok: !!r.ok, ms: r.ms || null, error: r.error || undefined })),
    });
    res.json({ ok: true });
  });

  /* Batch probe of arbitrary model ids — used by the "add models" dialog so
     the user can import only models that actually answer. Each model gets
     `attempts` tries (default 2) before being marked failed. */
  app.post('/api/providers/:id/test-models', async (req, res) => {
    const p = store.provider(req.params.id);
    if (!p) return res.status(404).json({ error: { message: 'Unknown provider.' } });
    let apiKey = null;
    try { apiKey = store.keyOf(p); } catch { return res.status(400).json({ error: { message: 'Stored key could not be decrypted — re-enter it.' } }); }
    // 1.8.0 (issue 8): no artificial 200-model cap, wider parallelism.
    const ids = Array.isArray(req.body?.models) ? req.body.models.map((x) => String(x || '').trim()).filter(Boolean).slice(0, 1500) : [];
    if (!ids.length) return res.status(400).json({ error: { message: 'models[] is required.' } });
    const prompt = typeof req.body?.message === 'string' && req.body.message.trim() ? req.body.message.trim() : 'Reply with exactly: ARCHX_OK';
    const concurrency = Math.max(1, Math.min(16, Number(req.body?.concurrency) || 8));
    const attempts = Math.max(1, Math.min(4, Number(req.body?.attempts) || 2));
    const results = new Array(ids.length).fill(null);
    let cursor = 0;
    const worker = async () => {
      for (;;) {
        const index = cursor++;
        if (index >= ids.length) return;
        const model = ids[index];
        const t0 = Date.now();
        try {
          const result = await withRetry(
            () => chatCompletion({ adapter: p.adapter, baseUrl: p.baseUrl, apiKey, model, messages: [{ role: 'user', content: prompt }], stream: false, temperature: 0, timeoutMs: 20000 }),
            { attempts }
          );
          results[index] = { model, ok: true, ms: Date.now() - t0, reply: result.text || '' };
        } catch (err) {
          results[index] = { model, ok: false, ms: Date.now() - t0, error: err.message };
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(concurrency, ids.length) }, () => worker()));
    const passed = results.filter((x) => x && x.ok).length;
    logger.log({ kind: 'model-test-batch', providerId: p.id, provider: p.name, status: 200, count: ids.length, passed, failed: ids.length - passed, attempts });
    res.json({ ok: true, results, passed, failed: ids.length - passed, count: ids.length, attempts });
  });


  app.post('/api/providers/:id/test-all', async (req, res) => {
    const p = store.provider(req.params.id);
    if (!p) return res.status(404).json({ error: { message: 'Unknown provider.' } });
    let apiKey = null;
    try { apiKey = store.keyOf(p); } catch { return res.status(400).json({ error: { message: 'Stored key could not be decrypted — re-enter it.' } }); }
    const ids = providerModelsOf(p).catalog;
    if (!ids.length) return res.status(400).json({ error: { message: 'No models are configured for this provider.' } });

    const concurrency = Math.max(1, Math.min(16, Number(req.body?.concurrency) || 8));
    const attempts = Math.max(1, Math.min(4, Number(req.body?.attempts) || 2));
    const results = [];
    let cursor = 0;

    /* 1.8.0 (issue 12): a provider-wide run produces ONE log row for all of
       its models (with a compact per-model summary inside), not one row per
       model. Individual user-initiated tests still log individually. */
    const worker = async () => {
      for (;;) {
        const index = cursor++;
        if (index >= ids.length) return;
        const model = ids[index];
        try {
          const r = await probeModel(p, apiKey, model, { attempts });
          results[index] = { model, ok: true, ms: r.ms, reply: String(r.reply || '').slice(0, 160), probe: r.kind };
        } catch (err) {
          results[index] = { model, ok: false, ms: null, error: err.message, status: err instanceof ProxyError ? err.status : 502 };
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(concurrency, ids.length) }, () => worker()));

    const hidden = new Set(providerModelsOf(p).hidden);
    const manual = new Set(p.freeOnlyManualEnabled || []);
    for (const result of results) {
      if (!result) continue;
      if (result.ok) { hidden.delete(result.model); manual.delete(result.model); }
      else { hidden.add(result.model); manual.delete(result.model); }
    }
    const models = providerModelsOf(p);
    p.models = { ...models, hidden: [...hidden], custom: models.custom };
    p.freeOnlyManualEnabled = [...manual];
    syncActiveSelection(store, p.id);
    persistProviders();
    const failed = results.filter((x) => x && !x.ok).length;
    const passed = results.length - failed;
    logger.log({
      kind: 'provider-test-all', providerId: p.id, provider: p.name, status: 200,
      count: results.length, passed, failed, concurrency,
      models: results.map((r) => ({ model: r.model, ok: !!r.ok, ms: r.ms || null, probe: r.probe || undefined, error: r.error || undefined })),
    });
    res.json({ ok: failed === 0, provider: providerView(p), results, passed, failed, count: results.length });
  });

  const removeProviderModels = (p, requestedIds) => {
    const ids = Array.from(new Set((Array.isArray(requestedIds) ? requestedIds : []).map((id) => String(id || '').trim()).filter(Boolean)));
    const cur = providerModelsOf(p);
    const existing = new Set([...cur.catalog, ...cur.custom]);
    const deleted = ids.filter((id) => existing.has(id));
    if (!deleted.length) return { deleted: [], missing: ids };
    const deletedSet = new Set(deleted);
    p.models = {
      ...cur,
      catalog: cur.catalog.filter((id) => !deletedSet.has(id)),
      hidden: cur.hidden.filter((id) => !deletedSet.has(id)),
      custom: cur.custom.filter((id) => !deletedSet.has(id)),
    };
    p.freeOnlyAutoHidden = (p.freeOnlyAutoHidden || []).filter((id) => !deletedSet.has(id));
    p.freeOnlyManualEnabled = (p.freeOnlyManualEnabled || []).filter((id) => !deletedSet.has(id));
    if (deletedSet.has(p.defaultModel)) p.defaultModel = null;
    store.state.providers.profiles = (store.state.providers.profiles || []).map((profile) => ({
      ...profile,
      items: (profile.items || []).map((item) => deletedSet.has(item.model) && item.providerId === p.id ? { ...item, enabled: false } : item),
    }));
    syncActiveSelection(store, p.id);
    return { deleted, missing: ids.filter((id) => !deletedSet.has(id)) };
  };

  app.post('/api/providers/:id/delete-model', async (req, res) => {
    const p = store.provider(req.params.id);
    if (!p) return res.status(404).json({ error: { message: 'Unknown provider.' } });
    const model = typeof req.body?.model === 'string' ? req.body.model.trim() : '';
    if (!model) return res.status(400).json({ error: { message: 'model is required.' } });
    const result = removeProviderModels(p, [model]);
    if (!result.deleted.length) return res.status(404).json({ error: { message: 'That model is not in this provider list.' } });
    persistProviders();
    logger.log({ kind: 'model-remove', providerId: p.id, provider: p.name, model });
    res.json({ provider: providerView(p), profiles: store.state.providers.profiles, active: store.state.providers.active, deleted: result.deleted });
  });

  app.post('/api/providers/:id/delete-models', async (req, res) => {
    const p = store.provider(req.params.id);
    if (!p) return res.status(404).json({ error: { message: 'Unknown provider.' } });
    const models = Array.isArray(req.body?.models) ? req.body.models : [];
    if (!models.length) return res.status(400).json({ error: { message: 'models[] is required.' } });
    const result = removeProviderModels(p, models);
    if (!result.deleted.length) return res.status(404).json({ error: { message: 'None of the selected models are in this provider list.' } });
    persistProviders();
    logger.log({ kind: 'model-remove-batch', providerId: p.id, provider: p.name, models: result.deleted, count: result.deleted.length });
    res.json({ provider: providerView(p), profiles: store.state.providers.profiles, active: store.state.providers.active, deleted: result.deleted, missing: result.missing });
  });

  // ---- api: studio (image / audio / vision surfaces, 1.8.0) ------------------
  const studioKey = (p) => {
    let apiKey = null;
    try { apiKey = store.keyOf(p); } catch { throw Object.assign(new Error('Stored key could not be decrypted — re-enter it.'), { status: 400 }); }
    return apiKey;
  };

  app.post('/api/providers/:id/generate-image', async (req, res) => {
    const p = store.provider(req.params.id);
    if (!p) return res.status(404).json({ error: { message: 'Unknown provider.' } });
    const model = String(req.body?.model || '').trim();
    const prompt = String(req.body?.prompt || '').trim();
    if (!model || !prompt) return res.status(400).json({ error: { message: 'model and prompt are required.' } });
    const t0 = Date.now();
    try {
      const apiKey = studioKey(p);
      const result = await generateImage({ adapter: p.adapter, baseUrl: p.baseUrl, apiKey, model, prompt, image: req.body?.image || undefined, imageMime: req.body?.imageMime || 'image/png' });
      logger.log({ kind: 'tool-image-gen', providerId: p.id, provider: p.name, model, status: 200, ms: Date.now() - t0 }, { request: { prompt: prompt.slice(0, 400), reference: !!req.body?.image }, response: { mime: result.mime, bytes: Math.round((result.base64 || '').length * 0.75) } });
      const artifactId = saveGeneratedAsset(store, result, prompt);
      res.json({ ok: true, artifactId, base64: result.base64, mime: result.mime, revisedPrompt: result.revisedPrompt || null, ms: Date.now() - t0 });
    } catch (err) {
      const status = err instanceof ProxyError ? err.status : Number(err.status) || 502;
      logger.log({ kind: 'tool-image-gen', providerId: p.id, provider: p.name, model, status, ms: Date.now() - t0, error: err.message });
      res.status(status).json({ error: { message: err.message } });
    }
  });

  app.post('/api/providers/:id/speech', async (req, res) => {
    const p = store.provider(req.params.id);
    if (!p) return res.status(404).json({ error: { message: 'Unknown provider.' } });
    const model = String(req.body?.model || '').trim();
    const input = String(req.body?.input || '').trim();
    if (!model || !input) return res.status(400).json({ error: { message: 'model and input are required.' } });
    const t0 = Date.now();
    try {
      const apiKey = studioKey(p);
      const result = await speech({ adapter: p.adapter, baseUrl: p.baseUrl, apiKey, model, input, voice: req.body?.voice || undefined });
      logger.log({ kind: 'tool-tts', providerId: p.id, provider: p.name, model, status: 200, ms: Date.now() - t0 }, { request: { input: input.slice(0, 400) }, response: { mime: result.mime, bytes: Math.round((result.base64 || '').length * 0.75) } });
      const artifactId = saveGeneratedAsset(store, result, input);
      res.json({ ok: true, artifactId, base64: result.base64, mime: result.mime, ms: Date.now() - t0 });
    } catch (err) {
      const status = err instanceof ProxyError ? err.status : Number(err.status) || 502;
      logger.log({ kind: 'tool-tts', providerId: p.id, provider: p.name, model, status, ms: Date.now() - t0, error: err.message });
      res.status(status).json({ error: { message: err.message } });
    }
  });

  app.post('/api/providers/:id/transcribe', async (req, res) => {
    const p = store.provider(req.params.id);
    if (!p) return res.status(404).json({ error: { message: 'Unknown provider.' } });
    const model = String(req.body?.model || '').trim();
    const audio = String(req.body?.audio || '');
    if (!model || !audio) return res.status(400).json({ error: { message: 'model and audio are required.' } });
    const t0 = Date.now();
    try {
      const apiKey = studioKey(p);
      const result = await transcribe({ adapter: p.adapter, baseUrl: p.baseUrl, apiKey, model, audio, mime: req.body?.mime || 'audio/mpeg' });
      logger.log({ kind: 'tool-stt', providerId: p.id, provider: p.name, model, status: 200, ms: Date.now() - t0 }, { response: { text: String(result.text || '').slice(0, 400) } });
      res.json({ ok: true, text: result.text, ms: Date.now() - t0 });
    } catch (err) {
      const status = err instanceof ProxyError ? err.status : Number(err.status) || 502;
      logger.log({ kind: 'tool-stt', providerId: p.id, provider: p.name, model, status, ms: Date.now() - t0, error: err.message });
      res.status(status).json({ error: { message: err.message } });
    }
  });

  // ---- api: web search tool (1.8.0, issue 11) --------------------------------
  app.post('/api/tools/web-search', async (req, res) => {
    const query = String(req.body?.query || '').trim();
    if (!query) return res.status(400).json({ error: { message: 'query is required.' } });
    const cfg = store.state.settings.search || {};
    const engines = Array.isArray(req.body?.engines) && req.body.engines.length ? req.body.engines : cfg.engines;
    const maxResults = Math.min(10, Math.max(1, Number(req.body?.maxResults) || Number(cfg.maxResults) || 5));
    const t0 = Date.now();
    const out = await webSearch(query, { engines, maxResults });
    logger.log({ kind: 'tool-web-search', status: out.ok ? 200 : 502, ms: Date.now() - t0, engine: out.engine || null, results: out.results.length, attempts: out.attempts }, { request: { query: query.slice(0, 300) }, response: { results: out.results.slice(0, maxResults) } });
    res.json({ ...out, query });
  });

  app.get('/api/tools/web-search/test', async (req, res) => {
    const out = await testEngines();
    res.json({ engines: out });
  });

  mountLibrary(app, store);

  // ---- api: memory / storage usage (1.8.0, issue 13) -------------------------
  const dirSize = (dir) => {
    let total = 0; let files = 0;
    const walk = (d) => {
      let entries = [];
      try { entries = fs.readdirSync(d, { withFileTypes: true }); } catch { return; }
      for (const e of entries) {
        const full = path.join(d, e.name);
        if (e.isDirectory()) walk(full);
        else if (e.isFile()) { try { total += fs.statSync(full).size; files += 1; } catch {} }
      }
    };
    walk(dir);
    return { bytes: total, files };
  };

  app.get('/api/memory-stats', (req, res) => {
    const out = { dir: store.dir, memoryOnly: store.memoryOnly, categories: [] };
    if (!store.dir || !store.db) {
      out.categories = [{ id: 'runtime', label: 'Runtime', detail: 'memory-only mode — nothing persisted', bytes: 0, count: 0 }];
      return res.json(out);
    }
    const dbSize = dirSize(store.dir).bytes - dirSize(path.join(store.dir, 'media')).bytes;
    const q = (sql) => { try { return store.db.prepare(sql).get(); } catch { return null; } };
    const chats = q('SELECT COUNT(*) AS n FROM chats')?.n || 0;
    const messages = q('SELECT COUNT(*) AS n FROM messages')?.n || 0;
    const msgBytes = q('SELECT COALESCE(SUM(LENGTH(content) + LENGTH(reasoning)),0) AS n FROM messages')?.n || 0;
    const logs = q('SELECT COUNT(*) AS n FROM request_logs')?.n || 0;
    const logBytes = q('SELECT COALESCE(SUM(LENGTH(payload_json)),0) AS n FROM request_logs')?.n || 0;
    const memories = q('SELECT COUNT(*) AS n FROM memories')?.n || 0;
    const assets = q('SELECT COUNT(*) AS n FROM assets')?.n || 0;
    const assetBytes = q('SELECT COALESCE(SUM(size_bytes),0) AS n FROM assets')?.n || 0;
    const img = q("SELECT COUNT(*) AS n FROM assets WHERE mime_type LIKE 'image/%'")?.n || 0;
    const vid = q("SELECT COUNT(*) AS n FROM assets WHERE mime_type LIKE 'video/%'")?.n || 0;
    const doc = assets - img - vid;
    const media = dirSize(path.join(store.dir, 'media'));
    out.categories = [
      { id: 'database', label: 'Database (SQLite)', detail: path.join(store.dir, 'archx.db'), bytes: dbSize, count: 1 },
      { id: 'chats', label: 'Chats & messages', detail: `${chats} chats · ${messages} messages`, bytes: msgBytes, count: chats },
      { id: 'logs', label: 'Request logs', detail: `${logs} entries`, bytes: logBytes, count: logs },
      { id: 'media-images', label: 'Image assets', detail: `${img} files on disk`, bytes: media.bytes, count: img },
      { id: 'media-videos', label: 'Video assets', detail: `${vid} files on disk`, bytes: 0, count: vid },
      { id: 'media-docs', label: 'Document / audio assets', detail: `${doc} records`, bytes: 0, count: doc },
      { id: 'memories', label: 'Memories', detail: `${memories} memory records`, bytes: 0, count: memories },
      { id: 'assets-total', label: 'Library total (files on disk)', detail: `${assets} assets · ${media.files} files`, bytes: assetBytes, count: assets },
    ];
    out.totalBytes = dbSize + media.bytes;
    res.json(out);
  });

  // ---- api: storage / wipe ---------------------------------------------------
  app.post('/api/storage', (req, res) => {
    const body = req.body || {};
    if (!('dir' in body)) {
      // 1.8.0 (issue 18): a missing `dir` key must NOT silently mean "memory-
      // only" — that used to switch areas and delete the old DB.
      return res.status(400).json({ error: { message: 'dir must be a path string or null.' } });
    }
    let target = body.dir;
    if (typeof target === 'string' && target.trim()) target = path.resolve(process.cwd(), target.trim());
    else if (target === null || target === '') target = null;
    else return res.status(400).json({ error: { message: 'dir must be a path string or null.' } });
    try {
      const report = store.migrateTo(target);
      logger.setStore(store);
      logger.log({ kind: 'storage-migrate', from: report.from, to: report.to, copied: report.copied, verified: report.verified });
      res.json({ ok: true, report, storage: storageView() });
    } catch (err) {
      logger.log({ kind: 'storage-migrate-failed', to: target, error: err.message });
      res.status(500).json({ error: { message: err.message }, storage: storageView() });
    }
  });

  const WIPE_SCOPES = ['all', 'keep-providers', 'chats', 'media-images', 'media-videos', 'media-docs', 'library'];
  app.post('/api/wipe', (req, res) => {
    const scope = typeof req.body?.scope === 'string' && WIPE_SCOPES.includes(req.body.scope) ? req.body.scope : 'all';
    store.wipe(scope);
    logger.setStore(store);
    logger.log({ kind: 'wipe', scope });
    res.json({ ok: true, scope });
  });


  /* 1.9.0 second web tool: read a page's text (modern UIs distinguish search
     vs read). Used automatically when the user message contains URLs while the
     Web toggle is on, and exposed at /api/tools/web-read. */
  const readPage = async (url) => {
    const t0 = Date.now();
    const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) ArchxAgent/1.9' }, redirect: 'follow', signal: AbortSignal.timeout ? AbortSignal.timeout(15000) : undefined });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const ct = String(res.headers.get('content-type') || '');
    let raw = await res.text();
    let title = '';
    if (ct.includes('html')) {
      const tm = raw.match(/<title[^>]*>([\s\S]{0,200}?)<\/title>/i);
      title = tm ? tm[1].replace(/\s+/g, ' ').trim() : '';
      raw = raw
        .replace(/<script[\s\S]*?<\/script>/gi, ' ')
        .replace(/<style[\s\S]*?<\/style>/gi, ' ')
        .replace(/<!--[\s\S]*?-->/g, ' ')
        .replace(/<[^>]+>/g, '\n')
        .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&#39;|&quot;/g, "'");
    }
    const text = raw.split(/\n+/).map((l) => l.trim()).filter(Boolean).join('\n').slice(0, 6000);
    return { url, title, text, chars: text.length, ms: Date.now() - t0 };
  };
  app.post('/api/tools/web-read', async (req, res) => {
    const url = String(req.body?.url || '').trim();
    if (!/^https?:\/\//.test(url)) return res.status(400).json({ error: { message: 'url must be http(s).' } });
    try { res.json({ ok: true, ...(await readPage(url)) }); }
    catch (err) { res.status(502).json({ error: { message: err.message } }); }
  });

  // ---- api: chat --------------------------------------------------------------
  app.post('/api/chat', async (req, res) => {
    const b = req.body || {};
    // Temporary means neither conversation data nor request payloads enter logs.
    const chatLogger = b.temporary === true ? { log() {} } : logger;
    if (!Array.isArray(b.messages) || !b.messages.length) {
      return res.status(400).json({ error: { message: 'messages[] is required.' } });
    }
    const modeId = typeof b.modeId === 'string' && b.modeId.trim() ? b.modeId.trim() : 'simple-chat';
    const existingChat = store.state.chats.chats.find(c => c.id === b.chatId);
    if (existingChat?.modeId && existingChat.modeId !== modeId) return res.status(409).json({ error: { message: 'Use the conversation’s saved mode.' } });
    const mode = getMode(modeId);
    if (!mode) return res.status(400).json({ error: { message: `Unknown chat mode “${modeId}”.` } });

    const requestedProfileId = b.profileId !== undefined ? b.profileId : (store.state.settings.advancedProfiles ? store.state.providers.activeProfileId : null);
    const profileId = requestedProfileId || null;
    const profile = profileId ? (store.state.providers.profiles || []).find((x) => x.id === profileId) : null;
    if (profileId && store.state.settings.advancedProfiles && !profile) {
      return res.status(404).json({ error: { message: 'Unknown model profile.' } });
    }
    const candidates = profile && store.state.settings.advancedProfiles
      ? [...profile.items]
        .filter((item) => { const provider = store.provider(item.providerId); return item.enabled !== false && !!provider && providerModelIsEnabled(provider, item.model); })
        .sort((a, c) => (Number(a.priority) || 1) - (Number(c.priority) || 1) || (Number(a.order) || 0) - (Number(c.order) || 0))
      : [{ providerId: b.providerId || store.state.providers.active.providerId, model: b.model || store.state.providers.active.model, priority: 1, order: 0 }];

    if (!candidates.length) return res.status(400).json({ error: { message: profile ? 'No profile models are currently available. Re-enable a paused model or re-enable a globally disabled model.' : 'No enabled model is selected.' } });

    const { temperature, maxTokens, stream } = b;
    const profileSettings = store.state.settings || {};
    const templateValues = {
      username: String(profileSettings.username ?? ''),
      age: String(profileSettings.age ?? ''),
      preferredName: String(profileSettings.preferredName || profileSettings.username || ''),
      agentName: String(profileSettings.agentName || 'Archx Agent'),
    };
    const expandPromptTemplate = (value) => String(value || '').replace(/\{\s*(username|age|preferredName|agentName)\s*\}/gi, (_, key) => templateValues[key.charAt(0).toLowerCase() + key.slice(1)] ?? '');
    const messages = Array.isArray(b.messages) ? b.messages.map((m) => ({ ...m })) : [];
    // System prompts are user-visible application state. Template tokens are
    // resolved on the server so the exact values sent upstream match the UI.
    const systemMessages = messages.filter((m) => m && m.role === 'system' && typeof m.content === 'string');
    systemMessages.forEach((m) => { m.content = expandPromptTemplate(m.content); });
    const personalizationLines = [
      templateValues.preferredName ? `User preferred name: ${templateValues.preferredName}` : '',
      templateValues.age ? `User age: ${templateValues.age}` : '',
      templateValues.agentName ? `Agent name: ${templateValues.agentName}` : '',
    ].filter(Boolean);
    if (systemMessages.length && personalizationLines.length) {
      const context = `\n\n[Archx personalization context]\n${personalizationLines.map((line) => `- ${line}`).join('\n')}\n[/Archx personalization context]`;
      systemMessages[0].content = `${systemMessages[0].content}${context}`;
    }
    const systemPromptIncluded = systemMessages.some((m) => m.content.trim());
    const systemPromptChars = systemMessages.reduce((a, m) => a + m.content.length, 0);
    const systemPromptId = typeof b.systemPromptId === 'string' && b.systemPromptId.trim() ? b.systemPromptId.trim() : null;
    const modeRequest = mode.prepareRequest({ messages, body: b, settings: store.state.settings, chatId: b.chatId || null });
    const requestMessages = Array.isArray(modeRequest?.messages) ? modeRequest.messages : messages;

    /* 1.8.0 (issue 11): the web-search tool — available in every mode. When
       the composer's Web toggle is on, the query runs through the free engine
       chain and the results are injected as a system message right before the
       request leaves the machine. */
    const chatId = typeof b.chatId === 'string' && b.chatId.trim() ? b.chatId.trim() : null;
    const traceId = 'chat-' + crypto.randomBytes(8).toString('hex');
    const toolEvents = [];
    if (b.useWebSearch === true && (store.state.settings.search || {}).enabled !== false) {
      const lastUser = [...messages].reverse().find((m) => m && m.role === 'user');
      const queryText = typeof lastUser?.content === 'string' ? lastUser.content.slice(0, 300) : '';
      if (queryText.trim()) {
        const sw = await webSearch(queryText, { engines: (store.state.settings.search || {}).engines, maxResults: Number((store.state.settings.search || {}).maxResults) || 5 });
        if (sw.ok && sw.results.length) {
          const ctx = [
            `[Archx web search — engine: ${sw.engine}, query: "${queryText.slice(0, 140)}"]`,
            ...sw.results.map((r, i) => `${i + 1}. ${r.title}\n   ${r.url}\n   ${r.snippet || ''}`),
            '[End web search results. Use them when relevant and cite sources by number.]',
          ].join('\n');
          requestMessages.push({ role: 'system', content: ctx });
          toolEvents.push({ kind: 'web-search', query: queryText, engine: sw.engine, ms: sw.ms, results: sw.results.slice(0, 8).map((r) => ({ title: r.title, url: r.url, snippet: (r.snippet || '').slice(0, 160) })) });
          chatLogger.log({ kind: 'tool-web-search', modeId, chatId, traceId, status: 200, engine: sw.engine, results: sw.results.length, ms: sw.ms }, { request: { query: queryText }, response: { results: sw.results } });
        } else {
          toolEvents.push({ kind: 'web-search', query: queryText, engine: null, error: sw.error || 'all engines failed' });
          chatLogger.log({ kind: 'tool-web-search', modeId, chatId, traceId, status: 502, error: sw.error || 'all engines failed', attempts: sw.attempts });
        }
      }
      /* tool 2: read pages the user linked (max 2) */
      const lastUser2 = [...messages].reverse().find((m) => m && m.role === 'user');
      const urls = typeof lastUser2?.content === 'string' ? (lastUser2.content.match(/https?:\/\/[^\s<>")]+/g) || []).slice(0, 2) : [];
      for (const url of urls) {
        try {
          const pg = await readPage(url);
          requestMessages.push({ role: 'system', content: `[Archx page read — ${pg.url}${pg.title ? ` — ${pg.title}` : ''}]\n${pg.text}\n[End page content.]` });
          toolEvents.push({ kind: 'web-read', url, title: pg.title, chars: pg.chars, ms: pg.ms });
          chatLogger.log({ kind: 'tool-web-read', modeId, chatId, traceId, status: 200, chars: pg.chars, ms: pg.ms }, { request: { url }, response: { title: pg.title } });
        } catch (err) {
          toolEvents.push({ kind: 'web-read', url, error: err.message });
          chatLogger.log({ kind: 'tool-web-read', modeId, chatId, traceId, status: 502, error: err.message });
        }
      }
    }

    const controller = new AbortController();
    res.on('close', () => { if (!res.writableEnded) controller.abort(); });
    const attempts = [];

    const resolveCandidate = (candidate) => {
      const provider = store.provider(candidate.providerId);
      if (!provider) throw Object.assign(new Error('Profile references a provider that no longer exists.'), { status: 404 });
      const model = candidate.model;
      if (!model) throw Object.assign(new Error('A profile entry is missing its model.'), { status: 400 });
      if (!providerModelIsEnabled(provider, model)) throw Object.assign(new Error(`Model “${model}” is disabled or not in this provider list.`), { status: 400 });
      let apiKey = null;
      try { apiKey = store.keyOf(provider); }
      catch { throw Object.assign(new Error('Stored key could not be decrypted on this machine — re-enter the key for this provider.'), { status: 400 }); }
      return { provider, model, apiKey };
    };

    if (stream) {
      res.writeHead(200, {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache, no-transform',
        Connection: 'keep-alive',
        'X-Accel-Buffering': 'no',
      });
      for (const ev of toolEvents) res.write(`data: ${JSON.stringify({ tool: ev })}\n\n`);

      for (let i = 0; i < candidates.length; i++) {
        const candidate = candidates[i];
        const t0 = Date.now();
        let buffered = [];
        let started = false;
        let usage = null;
        try {
          const target = resolveCandidate(candidate);
          const writeEvent = (payload) => res.write(`data: ${JSON.stringify(payload)}\n\n`);
          const commit = () => {
            if (started) return;
            started = true;
            for (const event of buffered) writeEvent(event);
            buffered = [];
          };
          const result = await chatCompletion(
            { adapter: target.provider.adapter, baseUrl: target.provider.baseUrl, apiKey: target.apiKey, model: target.model, messages: requestMessages, temperature, maxTokens, stream: true, signal: controller.signal },
            {
              onDelta: (text) => {
                const event = { object: 'chat.completion.chunk', choices: [{ index: 0, delta: { content: text } }] };
                if (!started) buffered.push(event); else writeEvent(event);
                if (!started) commit();
              },
              onReasoning: (text) => {
                const event = { object: 'chat.completion.chunk', choices: [{ index: 0, delta: { reasoning_content: text } }] };
                if (!started) buffered.push(event); else writeEvent(event);
                if (!started) commit();
              },
              onMeta: (meta) => { usage = meta.usage || usage; },
            }
          );
          if (!started) commit();
          usage = result.usage || usage;
          attempts.push({ provider: target.provider.name, providerId: target.provider.id, model: target.model, priority: candidate.priority || 1, status: 200, ms: Date.now() - t0 });
          writeEvent({ object: 'archx.meta', usage: usage || null, model: result.model || target.model, provider: target.provider.name, providerId: target.provider.id, profileId: profile?.id || null, fallbackIndex: i, fallbackUsed: i > 0, traceId });
          writeEvent({ object: 'archx.profile', id: profile?.id || null, usedProviderId: target.provider.id, usedModel: target.model, attempted: attempts, traceId });
          res.write('data: [DONE]\n\n');
          res.end();
          chatLogger.log({ kind: 'chat', traceId, chatId, modeId, providerId: target.provider.id, provider: target.provider.name, model: target.model, stream: true, status: 200, ms: Date.now() - t0, usage, profileId: profile?.id || null, systemPromptIncluded, systemPromptId, systemPromptChars, fallbackIndex: i, fallbackUsed: i > 0 }, { request: { modeId, providerId: target.provider.id, model: target.model, messages: requestMessages, temperature, maxTokens, stream: true, profileId: profile?.id || null }, response: { text: result.text, reasoning: result.reasoning, usage, model: result.model || target.model }, attempts });
          return;
        } catch (err) {
          const status = err instanceof ProxyError ? err.status : Number(err.status) || 502;
          attempts.push({ provider: err.provider || candidate.providerId, providerId: candidate.providerId, model: candidate.model, priority: candidate.priority || 1, status, ms: Date.now() - t0, error: err.message });
          if (controller.signal.aborted) {
            chatLogger.log({ kind: 'chat', traceId, chatId, modeId, providerId: candidate.providerId, model: candidate.model, stream: true, status: 499, ms: Date.now() - t0, error: 'client aborted', profileId: profile?.id || null }, { attempts });
            return res.end();
          }
          if (started || i === candidates.length - 1) {
            res.write(`data: ${JSON.stringify({ error: { message: err.message, status, providerId: candidate.providerId, model: candidate.model } })}\n\n`);
            res.write('data: [DONE]\n\n');
            res.end();
            chatLogger.log({ kind: 'chat', traceId, chatId, modeId, providerId: candidate.providerId, model: candidate.model, stream: true, status, ms: Date.now() - t0, error: err.message, profileId: profile?.id || null, systemPromptIncluded, systemPromptId, systemPromptChars }, { attempts, upstream: err.upstream });
            return;
          }
          const next = candidates[i + 1];
          res.write(`data: ${JSON.stringify({ object: 'archx.fallback', traceId, fallbackIndex: i + 1, failedProviderId: candidate.providerId, failedModel: candidate.model, error: err.message, nextProviderId: next?.providerId || null, nextModel: next?.model || null })}\n\n`);
          chatLogger.log({ kind: 'chat-fallback', traceId, chatId, providerId: candidate.providerId, model: candidate.model, status, ms: Date.now() - t0, error: err.message, profileId: profile?.id || null }, { upstream: err.upstream, attempts });
        }
      }
      return;
    }

    for (let i = 0; i < candidates.length; i++) {
      const candidate = candidates[i];
      const t0 = Date.now();
      try {
        const target = resolveCandidate(candidate);
        const result = await chatCompletion({ adapter: target.provider.adapter, baseUrl: target.provider.baseUrl, apiKey: target.apiKey, model: target.model, messages: requestMessages, temperature, maxTokens, stream: false, signal: controller.signal });
        attempts.push({ provider: target.provider.name, providerId: target.provider.id, model: target.model, priority: candidate.priority || 1, status: 200, ms: Date.now() - t0 });
        chatLogger.log({ kind: 'chat', traceId, chatId, modeId, providerId: target.provider.id, provider: target.provider.name, model: target.model, stream: false, status: 200, ms: Date.now() - t0, profileId: profile?.id || null, fallbackIndex: i, fallbackUsed: i > 0 }, { request: { modeId, providerId: target.provider.id, model: target.model, messages: requestMessages, temperature, maxTokens, stream: false, profileId: profile?.id || null }, response: result, attempts });
        return res.json({ object: 'chat.completion', modeId, model: target.model, provider: target.provider.name, providerId: target.provider.id, profileId: profile?.id || null, fallbackIndex: i, fallbackUsed: i > 0, traceId, attempts, tools: toolEvents.length ? toolEvents : undefined, choices: [{ index: 0, message: { role: 'assistant', content: result.text, reasoning_content: result.reasoning || undefined }, finish_reason: 'stop' }] });
      } catch (err) {
        const status = err instanceof ProxyError ? err.status : Number(err.status) || 502;
        attempts.push({ providerId: candidate.providerId, model: candidate.model, priority: candidate.priority || 1, status, ms: Date.now() - t0, error: err.message });
        if (controller.signal.aborted) return res.status(499).json({ error: { message: 'Client closed the request.' }, attempts });
        if (i === candidates.length - 1) {
          chatLogger.log({ kind: 'chat', traceId, chatId, modeId, providerId: candidate.providerId, model: candidate.model, stream: false, status, ms: Date.now() - t0, error: err.message, profileId: profile?.id || null, systemPromptIncluded, systemPromptId, systemPromptChars }, { attempts, upstream: err.upstream });
          return res.status(status).json({ error: { message: err.message, upstream: err.upstream }, attempts });
        }
        chatLogger.log({ kind: 'chat-fallback', traceId, chatId, providerId: candidate.providerId, model: candidate.model, status, ms: Date.now() - t0, error: err.message, profileId: profile?.id || null }, { attempts, upstream: err.upstream });
      }
    }
  });

  app.use((req, res) => res.status(404).json({ error: { message: `No route for ${req.method} ${req.path}` } }));

  return app;
}

function findPort(preferred, host) {
  const net = require('net');
  return new Promise((resolve, reject) => {
    const tryPort = (port, attempt) => {
      const srv = net.createServer();
      srv.unref();
      srv.on('error', () => {
        if (attempt > 15) return reject(new Error(`No free port found near ${preferred}.`));
        tryPort(port + 1, attempt + 1);
      });
      srv.listen(port, host, () => {
        srv.close(() => resolve(port));
      });
    };
    tryPort(preferred, 0);
  });
}

async function startServer(opts = {}) {
  const host = opts.host || '127.0.0.1';
  const port = await findPort(opts.port || 4173, host);
  const store = opts.store || new Store(opts.dataDir === undefined ? null : opts.dataDir);
  const app = createApp({ ...opts, store });
  const server = await new Promise((resolve, reject) => {
    const s = app.listen(port, host, () => resolve(s));
    s.on('error', reject);
    s.on('close', () => store.close());
  });
  const url = `http://${host === '0.0.0.0' ? '127.0.0.1' : host}:${port}`;
  return { server, url, port, host, store };
}

module.exports = { createApp, startServer };
